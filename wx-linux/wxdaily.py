#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日群聊总结
============

从 messages.db 取当天消息 -> 汇总成报告。
有 LLM key 就生成自然语言总结，没有就输出统计 + 原文摘要。

用法：
    python wxdaily.py                 # 今天
    python wxdaily.py --day 2026-11-13
    python wxdaily.py --chat 薛
"""

import argparse
import json
import sqlite3
import urllib.request
from collections import Counter
from datetime import date, datetime
from pathlib import Path

DB = "/root/dsh/wx-linux/messages.db"
CFG = Path("/root/dsh/wx-linux/config.json")


def load_llm():
    try:
        c = json.loads(CFG.read_text())
        l = c.get("llm", {})
        if l.get("api_key"):
            return l
    except Exception:
        pass
    return None


def fetch(day, chat=None):
    con = sqlite3.connect(DB)
    sql = "SELECT ts, type, text, src FROM msg WHERE day=?"
    args = [day]
    if chat:
        sql += " AND text LIKE ?"
        args.append(f"%{chat}%")
    sql += " ORDER BY ts"
    return con.execute(sql, args).fetchall()


def summarize_llm(llm, day, rows):
    lines = []
    for ts, typ, text, _ in rows:
        t = datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "?"
        lines.append(f"{t} {text}")
    body = "\n".join(lines)[:12000]
    prompt = (f"下面是微信群 {day} 的聊天记录，请用中文写一份简洁的当日总结：\n"
              f"1) 主要聊了什么（分主题，2-4 条）\n"
              f"2) 有没有需要跟进的事\n"
              f"3) 一句话概括\n\n聊天记录：\n{body}")
    req = urllib.request.Request(
        llm["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps({"model": llm.get("model", "deepseek-chat"),
                         "messages": [{"role": "user", "content": prompt}],
                         "temperature": 0.3, "max_tokens": 800}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + llm["api_key"]})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=date.today().isoformat())
    ap.add_argument("--chat", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rows = fetch(a.day, a.chat or None)
    print(f"{a.day} 共 {len(rows)} 条消息")
    if not rows:
        return

    kinds = Counter("系统" if t == 10000 else "文本" for _, t, _, _ in rows)
    print("类型分布:", dict(kinds))
    span = "—"
    if rows[0][0] and rows[-1][0]:
        span = (f"{datetime.fromtimestamp(rows[0][0]):%H:%M} — "
                f"{datetime.fromtimestamp(rows[-1][0]):%H:%M}")
    print("时间跨度:", span)

    llm = load_llm()
    if llm:
        print("\n生成总结中…")
        try:
            text = summarize_llm(llm, a.day, rows)
        except Exception as e:
            text = f"(LLM 调用失败: {e})"
    else:
        text = "（未配置 LLM key，下面是原文摘要）\n\n" + "\n".join(
            f"{datetime.fromtimestamp(ts):%H:%M} {t}" for ts, _, t, _ in rows[:80])

    print("\n" + "=" * 50)
    print(text)
    print("=" * 50)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"已写入 {a.out}")


if __name__ == "__main__":
    main()
