#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机器人健康面板：http://<ip>:3080/bot/"""
import json
import os
import re
import subprocess
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys as _sys
_sys.path.insert(0, '/root/dsh/wx-linux')

BOTLOG = "/root/dsh/wx-linux/logs/bot.log"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def status():
    st = {}
    st["time"] = datetime.now().strftime("%H:%M:%S")
    st["wechat_alive"] = bool(sh("pgrep -x wechat"))
    st["bot_service"] = sh("systemctl is-active wxbot")
    st["guard_service"] = sh("systemctl is-active wxguard")
    st["bot_proc"] = bool(sh("pgrep -f wxbot_run.py"))
    st["pages"] = len(os.listdir("/root/dsh/wx-linux/logs/pages")) if os.path.isdir("/root/dsh/wx-linux/logs/pages") else 0
    lines = []
    try:
        lines = open(BOTLOG, errors="replace").read().splitlines()[-200:]
    except OSError:
        pass
    st["last_msg"] = "-"
    st["last_reply"] = "-"
    for l in reversed(lines):
        if st["last_msg"] == "-" and "收到：" in l:
            st["last_msg"] = l[:19]
        if st["last_reply"] == "-" and ("已发：" in l or "发送状态未知：" in l):
            st["last_reply"] = l[:19]
        if st["last_msg"] != "-" and st["last_reply"] != "-":
            break
    st["need_phone"] = any("需要手机端验证" in l for l in lines[-10:])
    # 报告
    try:
        reps = [f for f in sorted(os.listdir("/root/dsh/wx-linux/reports"),
                                  reverse=True) if f.endswith(".md")][:8]
    except OSError:
        reps = []
    st["reports"] = reps
    try:
        import wxlog
        st["stats"] = wxlog.stats(24)
    except Exception:
        st["stats"] = {}
    st["recent"] = lines[-12:]
    return st


PAGE = """<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="10">
<title>微信机器人状态</title>
<style>body{{font:14px/1.7 -apple-system,"PingFang SC",sans-serif;background:#111;color:#ddd;padding:22px;max-width:760px;margin:auto}}
h2{{font-weight:500}}.k{{display:inline-block;width:130px;color:#888}}
.ok{{color:#7fd6a4}}.bad{{color:#ff7b72}}pre{{background:#1b1b1b;padding:12px;border-radius:8px;overflow:auto;font-size:12px;color:#aaa}}</style>
<h2>微信机器人状态</h2>
<div style="margin:14px 0 18px">
 <form method="post" action="/bot/toggle" style="display:inline">
  <button type="submit" style="font-size:16px;padding:10px 26px;border:none;border-radius:8px;cursor:pointer;background:{btn_bg};color:#fff">{btn}</button>
 </form>
</div>
<div><span class="k">时间</span>{time}</div>
<div><span class="k">微信进程</span>{w}</div>
<div><span class="k">机器人服务</span>{b}</div>
<div><span class="k">看护服务</span>{g}</div>
<div><span class="k">机器人进程</span>{p}</div>
<div><span class="k">捕获页数</span>{pages}</div>
<div><span class="k">最后收到</span>{lm}</div>
<div><span class="k">最后回复</span>{lr}</div>
<div><span class="k">需要手机处理</span>{need}</div>
<h3>近 24 小时</h3>
<div><span class="k">收到消息</span>{s_recv}</div>
<div><span class="k">回复成功</span>{s_ok}/{s_rep}</div>
<div><span class="k">平均感知延迟</span>{s_lat} s</div>
<div><span class="k">平均生成耗时</span>{s_gen} ms</div>
<div><span class="k">平均发送耗时</span>{s_snd} ms</div>
<div><span class="k">异常</span>{s_err}</div>
<h3>最近分析报告</h3><div>{reports}</div>
<h3>最近日志</h3><pre>{recent}</pre>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path == "/toggle":
            cur = sh("systemctl is-active wxbot")
            if cur == "active":
                subprocess.run("systemctl stop wxbot", shell=True)
            else:
                subprocess.run("systemctl start wxbot", shell=True)
            time.sleep(0.6)
            self.send_response(302)
            self.send_header("Location", "/bot/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/p/"):
            name = os.path.basename(self.path[3:])
            path = os.path.join("/root/dsh/wx-linux/reports/png", name)
            if os.path.isfile(path) and name.endswith(".png"):
                body = open(path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404); self.end_headers(); return
        if self.path.startswith("/h/"):
            name = os.path.basename(self.path[3:])
            path = os.path.join("/root/dsh/wx-linux/reports/html", name)
            if os.path.isfile(path) and name.endswith(".html"):
                body = open(path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404); self.end_headers(); return
        if self.path.startswith("/r/"):
            name = os.path.basename(self.path[3:])
            path = os.path.join("/root/dsh/wx-linux/reports", name)
            if os.path.isfile(path) and name.endswith(".md"):
                body = open(path, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404); self.end_headers(); return
        s = status()
        if self.path.startswith("/json"):
            body = json.dumps(s, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        ok = lambda v: f'<span class="ok">{"是" if v else "正常"}</span>' if v else '<span class="bad">否</span>'
        running = s["bot_service"] == "active"
        html = PAGE.format(
            btn=("🔴 停止机器人" if running else "🟢 启动机器人"),
            btn_bg=("#c0392b" if running else "#27ae60"),
            time=s["time"],
            w=ok(s["wechat_alive"]),
            b=f'<span class="{"ok" if s["bot_service"]=="active" else "bad"}">{s["bot_service"]}</span>',
            g=f'<span class="{"ok" if s["guard_service"]=="active" else "bad"}">{s["guard_service"]}</span>',
            p=ok(s["bot_proc"]),
            pages=s["pages"],
            lm=s["last_msg"], lr=s["last_reply"],
            need='<span class="bad">是（请手机处理）</span>' if s["need_phone"] else "否",
            s_recv=s.get("stats", {}).get("recv", 0),
            s_rep=s.get("stats", {}).get("reply", 0),
            s_ok=s.get("stats", {}).get("ok", 0),
            s_lat=s.get("stats", {}).get("avg_latency", 0),
            s_gen=s.get("stats", {}).get("avg_gen_ms", 0),
            s_snd=s.get("stats", {}).get("avg_send_ms", 0),
            s_err=s.get("stats", {}).get("err", 0),
            reports="".join(
                f'<div><a style="color:#76bad9" href="/bot/h/{n.replace(".md", ".html")}">'
                f'{n.replace(".md", "")}</a>'
                f' <a style="color:#e0893f;font-size:12px" href="/bot/p/{n.replace(".md", "")}-comic.png">漫画</a>'
                f' <a style="color:#4a9e6b;font-size:12px" href="/bot/p/{n.replace(".md", "")}.png">海报</a>'
                f' <a style="color:#555;font-size:12px" href="/bot/r/{n}">原文</a></div>'
                for n in s["reports"]) or "<div>（还没有报告）</div>",
            recent="\n".join(s["recent"]),
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8098), H).serve_forever()
