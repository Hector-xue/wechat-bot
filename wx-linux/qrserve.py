#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信登录二维码 · 实时查看页
===========================

浏览器打开 http://<服务器IP>:8099/ 就能看到虚拟屏的实时画面，
二维码过期会自动重启微信换一张新的（仅在"尚未登录"时生效）。

端点：
    /          自动每 2 秒刷新的页面
    /s.png     当前画面截图（1 秒节流）
    /status    JSON：亮度、是否已登录、微信进程是否活着
"""

import http.server
import json
import os
import re
import socketserver
import subprocess
import threading
import time

DISPLAY = ":99"
WECHAT_DIR = "/root/dsh/wx-linux/extracted/opt/wechat"
SHOT = "/root/dsh/wx-linux/live.png"
PORT = 8099
LOGIN_BRIGHTNESS = 0.25      # 平均亮度超过这个值就认为已进入主界面
RESTART_AFTER = 115          # 登录页停留超过这么多秒就换一张二维码

_env = {**os.environ, "DISPLAY": DISPLAY}
_lock = threading.Lock()
_state = {"shot_at": 0.0, "brightness": 0.0, "logged_in": False,
          "wechat_pid": 0, "restarts": 0, "last_launch": 0.0}


def sh(cmd, timeout=20):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, env=_env, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def wechat_pid() -> int:
    out = sh("pgrep -x wechat | head -1")
    return int(out) if out.isdigit() else 0


def start_wechat() -> None:
    sh(f"pgrep -x wechat | xargs -r kill; sleep 2")
    sh("mkdir -p /tmp/runtime-wx && chown wxuser:wxuser /tmp/runtime-wx && chmod 700 /tmp/runtime-wx")
    subprocess.Popen(
        "su - wxuser -c 'cd /opt/wechat && DISPLAY=:99 XDG_RUNTIME_DIR=/tmp/runtime-wx "
        "setsid nohup ./wechat >>/home/wxuser/wechat.log 2>&1 &'",
        shell=True, env=_env, start_new_session=True,
    )
    _state["last_launch"] = time.time()
    _state["restarts"] += 1


def capture(force: bool = False) -> str:
    """截图，1 秒内重复调用直接复用。返回文件路径。"""
    now = time.time()
    with _lock:
        if not force and now - _state["shot_at"] < 1.0 and os.path.exists(SHOT):
            return SHOT
        tmp = SHOT.replace(".png", "-tmp.png")
        sh(f"import -window root '{tmp}'", timeout=15)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 5000:
            os.replace(tmp, SHOT)
            _state["shot_at"] = now
            _state["brightness"] = measure(SHOT)
            if _state["brightness"] > LOGIN_BRIGHTNESS and _state["brightness"] < 0.99:
                _state["logged_in"] = True
    return SHOT


def measure(path: str) -> float:
    out = sh(f"convert '{path}' -colorspace Gray -format '%[fx:mean]' info:")
    try:
        return float(out)
    except ValueError:
        return 0.0


def watchdog() -> None:
    """没登录就定期换码；登录后就彻底不碰微信进程。"""
    while True:
        try:
            capture()
            _state["wechat_pid"] = wechat_pid()
            # 手动刹车：建了这个文件就永不重启微信
            if _state["logged_in"] or os.path.exists("/root/dsh/wx-linux/norestart"):
                time.sleep(10)
                continue
            if _state["wechat_pid"] == 0:
                start_wechat()
            elif time.time() - _state["last_launch"] > RESTART_AFTER:
                start_wechat()
        except Exception:
            pass
        time.sleep(8)


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="2">
<title>微信扫码登录</title>
<style>
 body{{margin:0;background:#111;color:#ddd;font:14px/1.6 -apple-system,"PingFang SC",sans-serif;
      display:flex;flex-direction:column;align-items:center;padding:18px}}
 h2{{margin:0 0 6px;font-weight:500}}
 .t{{font-size:13px;color:#888;margin-bottom:12px;text-align:center}}
 .t b{{color:#7fd6a4}}
 img{{max-width:96vw;border-radius:10px;box-shadow:0 6px 28px #0008;image-rendering:pixelated}}
 .bad{{color:#ffb86c}}
</style></head><body>
<h2>{title}</h2>
<div class="t">{hint}</div>
<img src="s.png?t={ts}" alt="screen">
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/s.png":
            p = capture()
            try:
                with open(p, "rb") as f:
                    self._send(200, "image/png", f.read())
            except OSError:
                self._send(500, "text/plain", b"capture failed")
            return
        if path == "/status":
            self._send(200, "application/json",
                       json.dumps(_state, ensure_ascii=False).encode())
            return

        st = _state
        if st["logged_in"]:
            title, hint = "已登录 ✓", "微信已进入主界面，可以关掉这个页面了"
        elif st["wechat_pid"] == 0:
            title, hint = "微信未运行", '正在拉起进程…'
        else:
            title = "用手机微信扫下面的码"
            hint = (f"二维码约 2 分钟过期，过期后本页会自动换新码"
                    f"（已换 {st['restarts']} 次）· 别点“Transfer files only”")
        html = PAGE.format(title=title, hint=hint, ts=int(time.time()))
        self._send(200, "text/html; charset=utf-8", html.encode())


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    _state["last_launch"] = time.time()
    capture(force=True)
    threading.Thread(target=watchdog, daemon=True).start()
    print(f"serving on :{PORT}", flush=True)
    Server(("0.0.0.0", PORT), Handler).serve_forever()
