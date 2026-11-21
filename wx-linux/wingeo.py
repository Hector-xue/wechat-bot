#!/usr/bin/env python3
"""查微信主窗口的真实几何（无窗口管理器，直接问 X）。"""
import sys
from Xlib import display, X

d = display.Display(":99")
root = d.screen().root

def walk(w, depth=0, out=None):
    out = out if out is not None else []
    try:
        for c in w.query_tree().children:
            try:
                name = c.get_wm_name() or ""
                cls = c.get_wm_class()
                g = c.get_geometry()
                tr = c.translate_coords(root, 0, 0)
                x, y = -tr.x, -tr.y
                if g.width > 400 and g.height > 300:
                    out.append((name, cls, x, y, g.width, g.height, c.id))
            except Exception:
                pass
            walk(c, depth+1, out)
    except Exception:
        pass
    return out

wins = walk(root)
wins.sort(key=lambda w: -w[4]*w[5])
for name, cls, x, y, w, h, wid in wins[:6]:
    print(f"name={name!r:20s} cls={cls} pos=({x},{y}) size={w}x{h} id=0x{wid:x}")
