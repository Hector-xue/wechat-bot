#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信守护进程（24×7）
====================

职责：
  1. Xvfb :99 挂了 -> 重新拉起
  2. 微信进程挂了 -> 清锁、重新拉起
  3. 停在登录页 -> 自动点 "Log in"（手机确认仍需人工）

用法：由 systemd 常驻运行
"""

import os
import subprocess
import time
from datetime import datetime

DISP = ":99"
WECHAT = "/opt/wechat"
LOG = "/root/dsh/wx-linux/logs/guard.log"


def log(msg):
    line = f"{datetime.now():%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def alive(pattern, exact=False):
    flag = "-x" if exact else "-f"
    return subprocess.run(f"pgrep {flag} '{pattern}' >/dev/null 2>&1",
                          shell=True).returncode == 0


def start_xvfb():
    log("拉起 Xvfb")
    env = "LD_LIBRARY_PATH=/opt/xvfb/usr/lib64"
    subprocess.Popen(
        f"{env} setsid nohup /opt/xvfb/usr/bin/Xvfb :99 "
        f"-screen 0 1400x900x24 -nolisten tcp >>/root/dsh/wx-linux/logs/xvfb.log 2>&1",
        shell=True, start_new_session=True)
    time.sleep(4)


def start_wechat():
    if alive("wechat", exact=True):
        return
    log("拉起微信")
    subprocess.run("pgrep -x wechat | xargs -r kill; sleep 1; rm -rf /tmp/.xwechat/lock",
                   shell=True)
    subprocess.Popen(
        "su - wxuser -c 'cd /opt/wechat && DISPLAY=:99 XDG_RUNTIME_DIR=/tmp/runtime-wx "
        "LD_PRELOAD=/root/dsh/wx-linux/sniffer.so "
        "setsid nohup ./wechat >>/home/wxuser/wechat.log 2>&1 &'",
        shell=True, start_new_session=True)
    time.sleep(14)


def windows():
    """返回 wechat 窗口 [(x, y, w, h)]"""
    try:
        from Xlib import display
        d = display.Display(DISP)
        root = d.screen().root
        out, stack = [], [root]
        while stack:
            w = stack.pop()
            try:
                for c in w.query_tree().children:
                    try:
                        if (c.get_wm_class() or ("", ""))[0] == "wechat":
                            g = c.get_geometry()
                            tr = c.translate_coords(root, 0, 0)
                            out.append((-tr.x, -tr.y, g.width, g.height))
                    except Exception:
                        pass
                    stack.append(c)
            except Exception:
                pass
        d.close()
        return out
    except Exception:
        return []


def try_login_click():
    """小窗口 = 登录页，点 Log in（有 no_autoclick 文件时跳过）"""
    if os.path.exists("/root/dsh/wx-linux/no_autoclick"):
        return False
    for x, y, w, h in windows():
        if w < 600 and h > 200:
            # 先 OCR 判断是不是"等待手机确认"，是就别乱点
            try:
                import wxread
                txt = " ".join(t for _, _, t, sc in
                               wxread.ocr(wxread.shot(), (x, y, x + w, y + h)) if sc > 0.5)
            except Exception:
                txt = ""
            if "Confirm" in txt or "确认" in txt:
                return False
            cx, cy = int(x + w * 0.5), int(y + h * 0.79)
            log(f"检测到登录页，点击 ({cx},{cy})")
            subprocess.run(
                f"DISPLAY={DISP} /root/dsh/wx-linux/venv/bin/python "
                f"/root/dsh/wx-linux/wxui.py click {cx} {cy} >/dev/null 2>&1",
                shell=True)
            return True
    return False


WECHAT_MD5 = "/root/dsh/wx-linux/wechat_bin.md5"
_last_ver_log = [0.0]


_bad_since = [0.0]


_bad_since = [0.0]


def check_need_human():
    """状态驱动：不在主界面超过 90 秒就告警（不依赖 OCR 关键词）"""
    try:
        import larkalert
    except Exception:
        return False
    ws = windows()
    big = [w for w in ws if w[2] >= 600 and w[3] >= 400]
    if big:
        _bad_since[0] = 0.0
        return False
    if not _bad_since[0]:
        _bad_since[0] = time.time()
    reason = "微信不在主界面（可能掉登录 / 窗口丢失 / 卡死）"
    for x, y, w, h in ws:
        if w < 600 and h > 200:
            try:
                import wxread
                txt = " ".join(t for _, _, t, sc in
                               wxread.ocr(wxread.shot(), (x, y, x + w, y + h)) if sc > 0.5)
            except Exception:
                txt = ""
            low = txt.lower()
            if "confirm" in low or "确认" in txt:
                if time.time() - _bad_since[0] > 30:
                    larkalert.send(f"⚠️ 微信机器人停在「等待手机确认」，请打开手机微信点确认。\n面板：{larkalert.PANEL}",
                                   key="phone_confirm", cooldown=1800)
                return True
            if "scan" in low or "扫码" in txt:
                reason = "微信已掉登录，需要重新扫码"
            elif any(k in low for k in ("security", "log in again", "重新登录", "登录失效", "已退出")):
                reason = "微信被风控登出，需要重新登录"
            break
    if time.time() - _bad_since[0] > 90:
        larkalert.send(f"⚠️ {reason}\n已持续 {int(time.time()-_bad_since[0])} 秒。\n面板：{larkalert.PANEL}",
                       key="not_ready", cooldown=1800)
        return True
    return False


def check_memory():
    """内存不足时重启微信（防 OOM），并飞书告警"""
    try:
        mem = {}
        for line in open("/proc/meminfo"):
            if ":" in line:
                k, v = line.split(":", 1)
                mem[k] = int(v.strip().split()[0])   # KB
        avail = mem.get("MemAvailable", 0)
        total = mem.get("MemTotal", 1)
        if avail < 250 * 1024:                        # 可用 < 250MB
            log(f"内存不足（可用 {avail // 1024}MB / {total // 1024}MB），重启微信")
            subprocess.run("pkill -x wechat", shell=True)
            try:
                import larkalert
                larkalert.send(f"⚠️ 服务器内存不足（可用 {avail // 1024}MB），已自动重启微信防 OOM。",
                               key="oom", cooldown=3600)
            except Exception:
                pass
            return True
    except Exception as e:
        log(f"内存检查异常: {e!r}")
    return False


def check_version():
    """微信二进制被更新/替换就报警"""
    import hashlib
    try:
        want = open(WECHAT_MD5).read().split()[0]
        h = hashlib.md5(open("/opt/wechat/wechat", "rb").read()).hexdigest()
        if h != want:
            if time.time() - _last_ver_log[0] > 3600:
                log(f"⚠️ 微信二进制指纹变了：期望 {want}，实际 {h}，可能被更新！")
                _last_ver_log[0] = time.time()
    except Exception as e:
        log(f"版本校验异常: {e!r}")


def main():
    log("守护启动")
    if not alive("Xvfb :99"):
        start_xvfb()
    start_wechat()
    last_login_click = 0
    last_beat = 0
    while True:
        try:
            if not alive("Xvfb :99"):
                start_xvfb()
            check_version()
            check_need_human()
            check_memory()
            if not alive("wechat", exact=True):
                log("检测到微信进程缺失")
                start_wechat()
            else:
                # 只在登录页时点，且最多每 60 秒一次
                if time.time() - last_login_click > 60:
                    if try_login_click():
                        last_login_click = time.time()
            if time.time() - last_beat > 1800:      # 每 30 分钟留一条心跳，证明循环还活着
                ws = windows()
                big = [w for w in ws if w[2] >= 600]
                log(f"心跳：主界面={'是' if big else '否'}，窗口数={len(ws)}")
                last_beat = time.time()
        except Exception as e:
            log(f"守护异常: {e!r}")
        time.sleep(10)


if __name__ == "__main__":
    os.makedirs("/root/dsh/wx-linux/logs", exist_ok=True)
    main()
