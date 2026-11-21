#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信 Linux 端 · 消息采集器
=========================

持续轮询目标会话，把 OCR 读到的消息落到本地 SQLite。
落库之后，"每日总结"就是一条 SQL，不再受"只能看屏幕"的限制。

用法：
    python wxcollect.py                      # 前台跑
    python wxcollect.py --chat "某某群" --interval 10
    python wxcollect.py --stats              # 只看库里的统计
"""

import argparse
import hashlib
import sqlite3
import time
from datetime import datetime, date
from pathlib import Path

import wxread
import wxui

DB = Path("/root/dsh/wx-linux/messages.db")
SCROLL_UP_XY = None      # 运行时按窗口算


def init():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS msg(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat TEXT NOT NULL,
        side TEXT NOT NULL,               -- self / other
        text TEXT NOT NULL,
        fp TEXT NOT NULL,                 -- 指纹，用于去重
        seen_at INTEGER NOT NULL,         -- 首次看到的时间戳
        day TEXT NOT NULL,
        UNIQUE(chat, fp)
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_day ON msg(day, chat)")
    con.commit()
    return con


def save(con, chat, msgs):
    now = int(time.time())
    today = date.today().isoformat()
    n = 0
    for m in msgs:
        fp = hashlib.md5(f"{chat}|{m['side']}|{m['text']}".encode()).hexdigest()
        try:
            cur = con.execute(
                "INSERT OR IGNORE INTO msg(chat,side,text,fp,seen_at,day) VALUES(?,?,?,?,?,?)",
                (chat, m["side"], m["text"], fp, now, today))
            n += max(cur.rowcount, 0)
        except sqlite3.Error:
            pass
    con.commit()
    return n


def scroll_up(px=3):
    """在聊天区滚轮上滚，用来补读更早的消息。"""
    from Xlib import X, display as xd
    from Xlib.ext import xtest
    d = xd.Display(wxread.DISP)
    x, y, w, h = wxread.geom()
    cx, cy = x + int(0.65 * w), y + int(0.45 * h)
    xtest.fake_input(d, X.MotionNotify, x=cx, y=cy); d.sync()
    time.sleep(0.15)
    for _ in range(px):
        xtest.fake_input(d, X.ButtonPress, 4); d.sync()
        xtest.fake_input(d, X.ButtonRelease, 4); d.sync()
        time.sleep(0.12)
    d.close()


def ensure_chat(chat):
    title = wxread.read_title()
    norm = lambda t: t.replace(" ", "").lower()
    if norm(chat) in norm(title):
        return True
    for x, y, text in wxread.list_sessions():
        if norm(chat) in text.replace(" ", "").lower():
            wxui.move_click(x, int(y))
            time.sleep(1.5)
            return norm(chat) in norm(wxread.read_title())
    return False


def run(chat, interval, catchup_every):
    con = init()
    print(f"采集开始：{chat}  轮询 {interval}s  库 {DB}", flush=True)
    last_new = time.time()
    n_scroll = 0
    while True:
        try:
            if not ensure_chat(chat):
                print("[警告] 切不到目标会话", flush=True)
                time.sleep(interval)
                continue
            msgs = wxread.read_chat()
            added = save(con, chat, msgs)
            if added:
                last_new = time.time()
                print(f"{datetime.now():%H:%M:%S} +{added} 条（本屏 {len(msgs)}）", flush=True)
            # 太久没有新消息 -> 往上翻，补读历史
            elif time.time() - last_new > 90 and n_scroll < 12:
                scroll_up(3)
                n_scroll += 1
                time.sleep(1.5)
                added = save(con, chat, wxread.read_chat())
                if added:
                    print(f"{datetime.now():%H:%M:%S} 回溯补到 +{added} 条", flush=True)
                    last_new = time.time()
                    n_scroll = 0
        except Exception as e:
            print(f"[异常] {e!r}", flush=True)
        time.sleep(interval)


def stats():
    con = init()
    rows = con.execute(
        "SELECT day, chat, COUNT(*) FROM msg GROUP BY day, chat ORDER BY day DESC LIMIT 15").fetchall()
    for d, c, n in rows:
        print(f"  {d}  {c[:24]:24s} {n:5d} 条")
    total = con.execute("SELECT COUNT(*) FROM msg").fetchone()[0]
    print(f"共 {total} 条")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", default="Tencent News")
    ap.add_argument("--interval", type=float, default=10)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    if a.stats:
        stats()
    else:
        run(a.chat, a.interval, 5)
