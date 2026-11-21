#!/usr/bin/env python3
"""在虚拟屏上点击/输入： wxclick.py click 700 400 | wxclick.py type 你好 """
import sys, time
from Xlib import display, X
from Xlib.ext import xtest
d = display.Display(":99")
def click(x, y):
    xtest.fake_input(d, X.MotionNotify, x=int(x), y=int(y)); d.sync()
    time.sleep(0.15)
    xtest.fake_input(d, X.ButtonPress, 1); d.sync(); time.sleep(0.08)
    xtest.fake_input(d, X.ButtonRelease, 1); d.sync()
def type_text(s):
    for ch in s:
        ks = d.keysym_to_keycode(ord(ch) if ord(ch) < 128 else 0)
        if ks: xtest.fake_input(d, X.KeyPress, ks); d.sync(); xtest.fake_input(d, X.KeyRelease, ks); d.sync()
cmd = sys.argv[1]
if cmd == "click": click(int(sys.argv[2]), int(sys.argv[3]))
else: type_text(" ".join(sys.argv[2:]))
print("ok")
