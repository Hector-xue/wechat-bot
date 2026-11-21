#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信 Linux 端 · 屏幕读取层（坐标自适应版）
=========================================

窗口位置和尺寸会变，所以每次都从 X 查真实几何，所有区域按比例算。
不碰数据库，靠 OCR 还原"谁说了什么"。
"""

import hashlib
import os
import re
import subprocess
import time

from PIL import Image
from rapidocr_onnxruntime import RapidOCR
from Xlib import display as xdisplay

DISP = ":99"
_engine = None
_geo_cache = {"t": 0.0, "g": None}


def engine():
    global _engine
    if _engine is None:
        _engine = RapidOCR()
    return _engine


def geom():
    """返回微信主窗口 (x, y, w, h)，2 秒内缓存。"""
    if time.time() - _geo_cache["t"] < 2 and _geo_cache["g"]:
        return _geo_cache["g"]
    d = xdisplay.Display(DISP)
    root = d.screen().root
    best = None
    stack = [root]
    while stack:
        w = stack.pop()
        try:
            for c in w.query_tree().children:
                try:
                    if (c.get_wm_class() or ("", ""))[0] == "wechat":
                        g = c.get_geometry()
                        tr = c.translate_coords(root, 0, 0)
                        box = (-tr.x, -tr.y, g.width, g.height)
                        if g.width * g.height > 80000:
                            if best is None or g.width * g.height > best[2] * best[3]:
                                best = box
                    stack.append(c)
                except Exception:
                    pass
        except Exception:
            pass
    d.close()
    if best is None:
        raise RuntimeError("找不到微信窗口")
    _geo_cache.update(t=time.time(), g=best)
    return best


def regions():
    x, y, w, h = geom()
    return {
        "header": (x + int(0.36 * w), y + int(0.05 * h), x + w, y + int(0.11 * h)),
        "chat": (x + int(0.36 * w), y + int(0.12 * h), x + w, y + int(0.86 * h)),
        "sessions": (x + int(0.05 * w), y + int(0.12 * h), x + int(0.36 * w), y + int(0.86 * h)),
        "input_xy": (x + int(0.62 * w), y + int(0.92 * h)),
        "session_x": x + int(0.20 * w),
    }


_shot_seq = [0]


def shot(path=None):
    """每次用独立文件名，避免多进程抢同一个临时文件"""
    if path is None:
        _shot_seq[0] += 1
        path = f"/tmp/wxshot_{os.getpid()}_{_shot_seq[0]}.png"
    subprocess.run(["import", "-window", "root", path],
                   env={"DISPLAY": DISP}, check=False)
    return path


def ocr(img_or_path, box=None):
    img = Image.open(img_or_path) if isinstance(img_or_path, str) else img_or_path
    if box:
        img = img.crop(tuple(map(int, box)))
    tmp = "/tmp/_ocr.png"
    img.save(tmp)
    res, _ = engine()(tmp, use_det=True, use_cls=False, use_rec=True)
    out = [(sum(p[0] for p in pts) / 4, sum(p[1] for p in pts) / 4, t.strip(), s)
           for pts, t, s in (res or [])]
    out.sort(key=lambda r: r[1])
    return out


# ---------------------------------------------------------------- 解析

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")
NOISE_RE = re.compile(r"^(Send|Search|##|#\S*)$")


def read_title():
    rows = ocr(shot(), regions()["header"])
    return "".join(t for _, _, t, s in rows if s > 0.5 and not NOISE_RE.match(t)).strip()


def read_chat():
    """返回聊天区最近的消息（自上而下），side: self/other。"""
    box = regions()["chat"]
    rows = ocr(shot(), box)
    pane_w = box[2] - box[0]
    mid = pane_w / 2
    msgs, cur = [], None
    for x, y, text, score in rows:
        if not text or score < 0.5 or TIME_RE.match(text) or NOISE_RE.match(text):
            continue
        side = "self" if x > mid else "other"
        if cur and cur["side"] == side and abs(y - cur["y_last"]) < 26:
            cur["text"] += " " + text
            cur["y_last"] = y
        else:
            if cur:
                msgs.append(cur)
            cur = {"side": side, "text": text, "y": y, "y_last": y}
    if cur:
        msgs.append(cur)
    for i, m in enumerate(msgs):
        m["key"] = hashlib.md5(f"{m['side']}|{m['text']}".encode()).hexdigest()[:12]
    return msgs


def list_sessions():
    """返回会话列表 [(绝对x, 绝对y, 文本)]。"""
    box = regions()["sessions"]
    rows = ocr(shot(), box)
    rx = regions()["session_x"]
    return [(rx, box[1] + y, t) for x, y, t, s in rows if t and s > 0.5]


if __name__ == "__main__":
    print("窗口:", geom())
    print("标题:", read_title())
    t0 = time.time()
    ms = read_chat()
    print(f"{time.time()-t0:.1f}s / {len(ms)} 条")
    for m in ms:
        print(f"  [{m['side']:5s}] {m['text'][:40]}")
