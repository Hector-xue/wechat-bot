#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增量批次群聊分析
================

借鉴 astrbot_plugin_qq_group_daily_analysis 的"增量分析模式"：
  * 滑动窗口：按累计消息数成批，而不是按自然日
  * 按量分批：累计到 batch_size 条才分析一批，控制 token
  * 自动去重：归一化后丢弃重复内容

用法：
    python wxanalyze.py --once            # 处理当前所有新消息
    python wxanalyze.py --min 20 --once   # 少于 20 条也分析
"""

import argparse
import json
import os
import re
import sqlite3
from collections import Counter
import urllib.request
from datetime import datetime

DB = "/root/dsh/wx-linux/messages.db"
OUTDIR = "/root/dsh/wx-linux/reports"
CFG = "/root/dsh/wx-linux/wbot.json"


def log(m):
    print(f"{datetime.now():%H:%M:%S} {m}", flush=True)


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS task(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL DEFAULT 'analyzing',
        first_id INTEGER, last_id INTEGER,
        batch_no INTEGER,
        n_raw INTEGER DEFAULT 0, n_dedup INTEGER DEFAULT 0,
        summary TEXT,                      -- LLM 快照
        md_file TEXT, html_file TEXT, png_file TEXT,
        error TEXT,
        created_at TEXT, updated_at TEXT)""")
    con.commit()
    con.execute("""CREATE TABLE IF NOT EXISTS report(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_no INTEGER, start_ts INTEGER, end_ts INTEGER,
        n_raw INTEGER, n_dedup INTEGER,
        summary TEXT, created_at TEXT)""")
    con.commit()


def new_task(con, first_id, last_id):
    now = datetime.now().isoformat(timespec="seconds")
    cur = con.execute("insert into task(state,first_id,last_id,created_at,updated_at)"
                      " values('analyzing',?,?,?,?)", (first_id, last_id, now, now))
    con.commit()
    return cur.lastrowid


def set_task(con, tid, **kw):
    kw["updated_at"] = datetime.now().isoformat(timespec="seconds")
    cols = ",".join(f"{k}=?" for k in kw)
    con.execute(f"update task set {cols} where id=?", (*kw.values(), tid))
    con.commit()


def recover_stale(con):
    """把中断的任务标记为 failed（保留快照供人工/下次复用）"""
    now = datetime.now().isoformat(timespec="seconds")
    cur = con.execute("update task set state='failed', error='中断'"
                      " where state in ('analyzing','rendering')").rowcount
    con.commit()
    if cur:
        log(f"标记 {cur} 个中断任务为 failed")
    return cur


def find_snapshot(con, first_id, last_id):
    """同一消息区间的既有快照（幂等复用，省 token）"""
    r = con.execute("select summary, md_file, html_file, png_file from task"
                    " where first_id=? and last_id=? and summary is not null"
                    " order by id desc limit 1", (first_id, last_id)).fetchone()
    return r


def get_meta(con, k, default=None):
    r = con.execute("select v from meta where k=?", (k,)).fetchone()
    return r[0] if r else default


def set_meta(con, k, v):
    con.execute("insert into meta(k,v) values(?,?) on conflict(k) do update set v=?", (k, v, v))
    con.commit()


def norm(t):
    return re.sub(r"[\s，。！？~～、,.!?\[\]【】]+", "", t or "")


def load_llm():
    try:
        c = json.loads(open(CFG).read())
        if c.get("api_key"):
            return c["api_key"], c.get("model", "deepseek-chat")
    except Exception:
        pass
    try:
        for line in open("/root/.dsh/.credentials.yaml"):
            if line.strip().startswith("DEEPSEEK_API_KEY:"):
                return line.split(":", 1)[1].strip().strip("\"'"), "deepseek-chat"
    except OSError:
        pass
    return None, None


def ask(key, model, msgs):
    body = json.dumps({"model": model, "messages": msgs,
                       "temperature": 0.4, "max_tokens": 900}).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


SENDER_RE = re.compile(r"^([A-Za-z0-9_\-]{4,64}):\s*\n(.+)$", re.S)
NOISE_RE = re.compile(r"^\[(图片|语音|表情|文件|链接|视频|动画|位置|名片|转账|红包|小程序|音乐|聊天记录|引用|笔记|动画表情|链接失效)\]$")


def is_noise(text):
    t = (text or "").strip()
    return not t or bool(NOISE_RE.match(t))


def split_sender(text):
    m = SENDER_RE.match(text or "")
    if m:
        return m.group(1), m.group(2).strip()
    return "", text


def keep_by_mode(text, mode):
    """group: 只保留带发送者前缀的群消息；direct: 反之；all: 全要"""
    m = SENDER_RE.match(text or "")
    if mode == "group":
        return m.group(2).strip() if m else None
    if mode == "direct":
        return None if m else text
    return text


def analyze(con, batch_size, min_batch, recent=0, mode="group", today=0):
    """today>0 总结当日；recent>0 分析最近 N 条；否则按水位线增量"""
    if today:
        n = datetime.now()
        midnight = int(datetime(n.year, n.month, n.day).timestamp())
        rows = con.execute(
            "select id, ts, text from msg where ts >= ? order by id", (midnight,)).fetchall()
    elif recent:
        rows = con.execute(
            "select id, ts, text from msg order by id desc limit ?", (recent,)).fetchall()
        rows = list(reversed(rows))
    else:
        last = int(get_meta(con, "last_msg_id", "0"))
        rows = con.execute(
            "select id, ts, text from msg where id > ? order by id", (last,)).fetchall()
    label = "今日" if today else ("最近" if recent else "新")
    log(f"{label}消息 {len(rows)} 条")
    if len(rows) < batch_size and len(rows) < min_batch:
        log("不够一批，跳过")
        return False

    first_id = rows[0][0] if rows else 0
    last_id = rows[-1][0] if rows else 0

    # 幂等：同一区间已有快照就直接复用（省 token）
    snap = find_snapshot(con, first_id, last_id)
    if snap and snap[0]:
        log("命中快照，复用（不重烧 token）")
        summary = snap[0]
        start_ts = rows[0][1] if rows else 0
        end_ts = rows[-1][1] if rows else 0
        batch_no = int(get_meta(con, "batch_no", "0")) + 1
        md_file = _render_files(con, batch_no, start_ts, end_ts, len(rows), len(rows), summary)
        set_task(con, _latest_task(con), state="done", summary=summary,
                 md_file=md_file)
        log(f"批次 #{batch_no} 复用完成 → {md_file}")
        return True

    seen, kept, dropped, senders = set(), [], 0, []
    for rid, ts, text in rows:
        sender, _ = split_sender(text)
        t2 = keep_by_mode(text, mode)
        if t2 is None or is_noise(t2):
            dropped += 1
            continue
        k = norm(t2)
        if not k or k in seen:
            dropped += 1
            continue
        seen.add(k)
        kept.append((rid, ts, t2))
        senders.append(sender)
    log(f"去重后 {len(kept)} 条（丢弃 {dropped} 条重复）")

    if not kept:
        log("没有有效消息")
        return False

    key, model = load_llm()
    if not key:
        log("没有 LLM key")
        return False

    tid = new_task(con, first_id, last_id)
    try:
        lines = [f"{datetime.fromtimestamp(ts):%H:%M} {t}" if ts else t for _, ts, t in kept]
        body = "\n".join(lines)[:14000]
        prompt = (f"下面是微信群的一批聊天记录（共 {len(kept)} 条，已去重）。请用中文输出一份简洁分析：\n"
                  f"1. 主要话题（2-4 条，每条一句话）\n"
                  f"2. 值得记的金句（最多 3 条，直接引用原文）\n"
                  f"3. 一句话概括这段时间群里在干嘛\n"
                  f"不要编造，只依据下面的记录。\n\n{body}")
        summary = ask(key, model, [{"role": "user", "content": prompt}])
        # 用户画像：谁最活跃（确定性，不额外烧 token）
        try:
            import wxnames
            nmap = wxnames.load()
        except Exception:
            nmap = {}
        cnt = Counter(x for x in senders if x)
        top = cnt.most_common(5)
        if top:
            rows_p = "\n".join(f"- {wxnames.resolve(x, nmap)}：{c} 条" for x, c in top)
            summary = summary.rstrip() + f"\n\n## 4. 谁最活跃\n{rows_p}"
        # 快照：LLM 结果立刻落盘，之后崩了也能复用
        set_task(con, tid, state="rendering", summary=summary,
                 n_raw=len(rows), n_dedup=len(kept))
    except Exception as e:
        set_task(con, tid, state="failed", error=str(e)[:200])
        log(f"LLM 失败: {e}")
        return False

    start_ts = kept[0][1] if kept else 0
    end_ts = kept[-1][1] if kept else 0
    batch_no = int(get_meta(con, "batch_no", "0")) + 1
    con.execute("insert into report(batch_no,start_ts,end_ts,n_raw,n_dedup,summary,created_at)"
                " values(?,?,?,?,?,?,?)",
                (batch_no, start_ts, end_ts, len(rows), len(kept), summary,
                 datetime.now().isoformat(timespec="seconds")))
    if not recent and not today:
        set_meta(con, "last_msg_id", str(kept[-1][0]))
        set_meta(con, "batch_no", str(batch_no))
        con.commit()

    md_file = _render_files(con, batch_no, start_ts, end_ts, len(rows), len(kept), summary)
    set_task(con, tid, state="done", md_file=md_file)
    log(f"批次 #{batch_no} 完成 → {md_file}")
    return True


def _render_files(con, batch_no, start_ts, end_ts, n_raw, n_dedup, summary):
    os.makedirs(OUTDIR, exist_ok=True)
    fn = f"{OUTDIR}/{datetime.now():%Y%m%d-%H%M}-b{batch_no}.md"
    with open(fn, "w") as f:
        f.write(f"# 群聊分析 批次 #{batch_no}\n\n")
        f.write(f"- 时间范围：{datetime.fromtimestamp(start_ts):%m-%d %H:%M} — "
                f"{datetime.fromtimestamp(end_ts):%m-%d %H:%M}\n")
        f.write(f"- 原始 {n_raw} 条，去重后 {n_dedup} 条\n\n")
        f.write(summary + "\n")
    try:
        import wxreport
        h = wxreport.render(fn)
    except Exception as e:
        log(f"HTML 渲染失败: {e}")
    try:
        import wxposter
        wxposter.render(fn)
    except Exception as e:
        log(f"海报生成失败: {e}")
    try:
        import wxcomic
        wxcomic.render(fn)
    except Exception as e:
        log(f"漫画生成失败: {e}")
    return fn


def _latest_task(con):
    r = con.execute("select id from task order by id desc limit 1").fetchone()
    return r[0] if r else None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=200)
    ap.add_argument("--min", type=int, default=20, dest="min_batch")
    ap.add_argument("--mode", choices=["group", "direct", "all"], default="group",
                    help="group=只分析群消息（带发送者前缀）")
    ap.add_argument("--recent", type=int, default=0, help="只分析最近 N 条，不动水位线")
    ap.add_argument("--today", action="store_true", help="总结当日（从今天 0 点到现在）")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--recover", action="store_true", help="标记中断任务为 failed")
    a = ap.parse_args()
    con = sqlite3.connect(DB)
    init(con)
    if a.recover:
        n = recover_stale(con)
        print(f"恢复完成：{n} 个中断任务已标记 failed")
        raise SystemExit(0)
    if a.once:
        analyze(con, a.batch, a.min_batch, recent=a.recent, mode=a.mode,
                today=1 if a.today else 0)
