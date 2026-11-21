#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""虚拟屏操作小工具：点击 / 打字 / 按键 / 截图。坐标基于 1400x900。"""
import subprocess
import sys
import time

from Xlib import X, display
from Xlib.ext import xtest

DISP = ":99"
d = display.Display(DISP)


def move_click(x, y):
    xtest.fake_input(d, X.MotionNotify, x=int(x), y=int(y)); d.sync()
    time.sleep(0.2)
    xtest.fake_input(d, X.ButtonPress, 1); d.sync(); time.sleep(0.08)
    xtest.fake_input(d, X.ButtonRelease, 1); d.sync(); time.sleep(0.2)


def type_ascii(s):
    for ch in s:
        ks = d.keysym_to_keycode(ord(ch))
        if not ks:
            continue
        shift = ch.isupper() or ch in '~!@#$%^&*()_+{}|:"<>?'
        sh = d.keysym_to_keycode(0xffe1)
        if shift:
            xtest.fake_input(d, X.KeyPress, sh); d.sync()
        xtest.fake_input(d, X.KeyPress, ks); d.sync()
        xtest.fake_input(d, X.KeyRelease, ks); d.sync()
        if shift:
            xtest.fake_input(d, X.KeyRelease, sh); d.sync()
        time.sleep(0.02)


KEYS = {"enter": 0xff0d, "tab": 0xff09, "esc": 0xff1b,
        "backspace": 0xff08, "ctrl_a": None, "ctrl_v": None}


def press(name):
    if name in ("ctrl_a", "ctrl_v"):
        ctrl = d.keysym_to_keycode(0xffe3)
        a = d.keysym_to_keycode(ord("a" if name == "ctrl_a" else "v"))
        xtest.fake_input(d, X.KeyPress, ctrl); d.sync()
        xtest.fake_input(d, X.KeyPress, a); d.sync()
        xtest.fake_input(d, X.KeyRelease, a); d.sync()
        xtest.fake_input(d, X.KeyRelease, ctrl); d.sync()
        return
    ks = d.keysym_to_keycode(KEYS[name])
    xtest.fake_input(d, X.KeyPress, ks); d.sync(); time.sleep(0.05)
    xtest.fake_input(d, X.KeyRelease, ks); d.sync()
    time.sleep(0.1)


def shot(path):
    subprocess.run(["import", "-window", "root", path],
                   env={"DISPLAY": DISP}, check=False)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "click":
        move_click(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "type":
        type_ascii(" ".join(sys.argv[2:]))
    elif cmd == "key":
        press(sys.argv[2])
    elif cmd == "shot":
        shot(sys.argv[2])
    print("ok")

def scroll(x, y, clicks=5, up=True):
    from Xlib import X as _X
    d2 = d
    xtest.fake_input(d2, _X.MotionNotify, x=int(x), y=int(y)); d2.sync()
    time.sleep(0.1)
    btn = 4 if up else 5
    for _ in range(clicks):
        xtest.fake_input(d2, _X.ButtonPress, btn); d2.sync()
        xtest.fake_input(d2, _X.ButtonRelease, btn); d2.sync()
        time.sleep(0.12)

def right_click(x, y):
    xtest.fake_input(d, X.MotionNotify, x=int(x), y=int(y)); d.sync()
    time.sleep(0.2)
    xtest.fake_input(d, X.ButtonPress, 3); d.sync(); time.sleep(0.08)
    xtest.fake_input(d, X.ButtonRelease, 3); d.sync(); time.sleep(0.3)


def focus_wechat():
    """Xvfb 没有窗口管理器，必须显式把输入焦點给微信窗口"""
    from Xlib import display as _xd, X as _X
    d2 = _xd.Display(":99")
    root = d2.screen().root
    stack, best = [root], None
    while stack:
        w = stack.pop()
        try:
            for c in w.query_tree().children:
                try:
                    if (c.get_wm_class() or ("", ""))[0] == "wechat":
                        g = c.get_geometry()
                        if g.width * g.height > 80000:
                            best = c
                except Exception:
                    pass
                stack.append(c)
        except Exception:
            pass
    if best is not None:
        try:
            best.configure(stack_mode=_X.Above)
            d2.set_input_focus(best, _X.RevertToParent, _X.CurrentTime)
            d2.sync()
        except Exception:
            pass
    d2.close()
    return best is not None

def focus_wechat():
    """把输入焦点给微信主窗口（不点击、不改界面），让它保持活跃"""
    try:
        from Xlib import display as xd, X
        d = xd.Display(DISP)
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
                            if g.width * g.height > 200000:
                                best = c
                    except Exception:
                        pass
                    stack.append(c)
            except Exception:
                pass
        if best is not None:
            best.set_input_focus(X.RevertToParent, X.CurrentTime)
            d.sync()
        d.close()
        return True
    except Exception:
        return False
