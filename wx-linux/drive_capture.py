import subprocess, time
import wxui

wxui.move_click(420, 330)          # 打开会话列表第一行
time.sleep(2)
wxui.move_click(1120, 160)         # 聊天区右上角搜索
time.sleep(1.5)
subprocess.run("printf 的 | DISPLAY=:99 xclip -selection clipboard -i", shell=True)
wxui.press("ctrl_v")
time.sleep(5)
for i in range(4):
    wxui.scroll(860, 400, clicks=6, up=True)
    time.sleep(0.7)
