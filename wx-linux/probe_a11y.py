import sys
import pyatspi
desktop = pyatspi.Registry.getDesktop(0)
print(f"桌面应用数: {len(desktop)}")
count = 0
def walk(node, depth=0):
    global count
    if count > 400 or depth > 12:
        return
    try:
        role = node.getRoleName()
        name = (node.name or "").replace("\n", " ")[:60]
        txt = ""
        try:
            t = node.queryText()
            if t and t.characterCount:
                txt = t.getText(0, min(t.characterCount, 80)).replace("\n", " ")
        except Exception:
            pass
        if name or txt:
            print("  " * depth + f"{role}: {name!r} {('TEXT=' + repr(txt)) if txt else ''}")
            count += 1
        for c in node:
            walk(c, depth + 1)
    except Exception:
        pass
for app in desktop:
    try:
        print(f"--- 应用: {app.name}")
        walk(app)
    except Exception as e:
        print("err", e)
