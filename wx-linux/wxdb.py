#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把截获的明文页固化成本地消息库
================================

数据来源：sniffer.so 在微信进程内 hook pread64 抓到的解密页
           logs/pages/*.bin + logs/pages_meta.jsonl

输出：messages.db
    msg(ts, type, text, chat_hint, src, seen_at)
    session(name, preview, ts_raw)
"""

import json
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, "/root/dsh/wx-linux")
from pageparse import parse_leaf  # noqa: E402

PAGES = "/root/dsh/wx-linux/logs/pages"
META = "/root/dsh/wx-linux/logs/pages_meta.jsonl"
DB = "/root/dsh/wx-linux/messages.db"


def init():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS msg(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER, type INTEGER, text TEXT,
        day TEXT, src TEXT,
        UNIQUE(text, ts))""")
    con.execute("""CREATE TABLE IF NOT EXISTS session(
        name TEXT, preview TEXT, ts_raw INTEGER,
        UNIQUE(name, preview))""")
    con.commit()
    return con


def main():
    con = init()
    raw = [json.loads(l) for l in open(META) if '"file"' in l]
    latest = {}
    for r in raw:
        latest[r["file"]] = r        # 同名文件以最后一条为准
    meta = list(latest.values())
    n_msg = n_sess = 0
    for m in meta:
        path = f"{PAGES}/{m['file']}"
        rows = parse_leaf(path)
        if not rows:
            continue
        is_msg = "message_0.db" in m["db"] and not m["db"].endswith("-wal")
        is_sess = m["db"].endswith("session.db")
        for rowid, vals in rows:
            if is_msg and len(vals) >= 13:
                typ = vals[2] if isinstance(vals[2], int) else -1
                ts = vals[5] if isinstance(vals[5], int) else 0
                text = vals[12] if isinstance(vals[12], str) else ""
                if not text or text.startswith("<msgsource>"):
                    continue
                day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
                cur = con.execute(
                    "INSERT OR IGNORE INTO msg(ts,type,text,day,src) VALUES(?,?,?,?,?)",
                    (ts, typ, text, day, m["db"].split("/")[-1]))
                n_msg += max(cur.rowcount, 0)
            elif is_sess and len(vals) >= 3:
                name = str(vals[0]) if vals[0] else ""
                preview = str(vals[1]) if len(vals) > 1 and vals[1] else ""
                if name:
                    con.execute(
                        "INSERT OR IGNORE INTO session(name,preview) VALUES(?,?)",
                        (name, preview))
                    n_sess += 1
    con.commit()
    print(f"新增消息 {n_msg} 条，会话记录 {n_sess} 条")
    print("\n=== 最近消息 ===")
    for ts, typ, text in con.execute(
            "SELECT ts,type,text FROM msg ORDER BY ts DESC LIMIT 15"):
        t = datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "?"
        kind = "系统" if typ == 10000 else "文本"
        print(f"  {t} [{kind}] {text[:60]}")
    print("\n=== 库内统计 ===")
    for day, n in con.execute(
            "SELECT day, COUNT(*) FROM msg WHERE day<>'' GROUP BY day ORDER BY day DESC"):
        print(f"  {day}: {n} 条")


if __name__ == "__main__":
    main()
