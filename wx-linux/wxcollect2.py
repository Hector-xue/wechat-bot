#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
采集循环：定期驱动微信读盘 -> 拦截库落页 -> 入库
================================================

为什么要"驱动"：微信把消息页缓存在内存里，不主动重读磁盘。
定期打开目标会话 + 轻微滚动，能让它从磁盘加载页，正好被 sniffer 接住。

用法：
    python wxcollect2.py --chats "群A,群B" --interval 90
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, "/root/dsh/wx-linux")
import wxread  # noqa: E402
import wxui    # noqa: E402

PAGES = "/root/dsh/wx-linux/logs/pages"


def log(m):
    print(f"{datetime.now():%H:%M:%S} {m}", flush=True)


def open_chat(name):
    try:
        if name.replace(" ", "") in wxread.read_title().replace(" ", ""):
            return True
    except Exception:
        pass
    for x, y, t in wxread.list_sessions():
        if name.replace(" ", "") in t.replace(" ", ""):
            wxui.move_click(x, int(y))
            time.sleep(2)
            return True
    return False


def drive(name):
    """打开会话并来回滚动，逼它读盘"""
    if not open_chat(name):
        log(f"找不到会话 {name}")
        return False
    x, y, w, h = wxread.geom()
    cx, cy = x + int(0.65 * w), y + int(0.45 * h)
    for _ in range(4):
        wxui.scroll(cx, cy, clicks=8, up=True)
        time.sleep(0.5)
    for _ in range(2):
        wxui.scroll(cx, cy, clicks=6, up=False)
        time.sleep(0.5)
    return True


def ingest():
    r = subprocess.run(
        ["/root/dsh/wx-linux/venv/bin/python", "-u", "/root/dsh/wx-linux/wxdb.py"],
        capture_output=True, text=True, timeout=300)
    for line in (r.stdout or "").splitlines():
        if line.startswith("新增"):
            log(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chats", default="")
    ap.add_argument("--interval", type=int, default=90)
    a = ap.parse_args()
    chats = [c.strip() for c in a.chats.split(",") if c.strip()]
    if not chats:
        log("没有指定会话，退出")
        return
    log(f"开始值守：{chats}，间隔 {a.interval}s")
    while True:
        for c in chats:
            drive(c)
        ingest()
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
