#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信 Linux 端 · 群聊插话机器人（主循环）
=======================================

链路：截图聊天区 → OCR 还原消息 → 判官模型决定插不插话 → 剪贴板+Ctrl+V 发送

用法：
    python wxbot.py                  # 按 config.json 跑
    python wxbot.py --dry-run        # 只打印不发送（第一次一定先用这个）
    python wxbot.py --once           # 只跑一轮，方便调试
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import wxread
import wxui

HERE = Path(__file__).resolve().parent
DEFAULT = {
    "target_chat": "Tencent News",
    "persona": "你是群里的一个普通成员，说话短、口语、会接梗，从不自我介绍，从不提自己是 AI。",
    "llm": {"base_url": "https://api.deepseek.com/v1", "api_key": "", "model": "deepseek-chat",
            "judge_model": "deepseek-chat", "temperature": 1.1, "max_tokens": 120},
    "behavior": {"poll_seconds": 12, "context_size": 10, "reply_cooldown_seconds": 120,
                 "max_per_hour": 6, "quiet_hours": [1, 8], "max_reply_chars": 50},
    "safety": {"dry_run": True},
}



def log(tag, msg):
    print(f"{datetime.now():%H:%M:%S} [{tag}] {msg}", flush=True)


def load_cfg(p):
    cfg = dict(DEFAULT)
    if Path(p).exists():
        user = json.loads(Path(p).read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg


class LLM:
    def __init__(self, cfg):
        self.c = cfg

    def chat(self, messages, model=None, temperature=None, max_tokens=None):
        if not self.c.get("api_key"):
            return ""
        body = {"model": model or self.c["model"], "messages": messages,
                "temperature": self.c.get("temperature", 1.1) if temperature is None else temperature,
                "max_tokens": max_tokens or self.c.get("max_tokens", 120)}
        req = urllib.request.Request(
            self.c["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.c["api_key"]})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return (json.loads(r.read())["choices"][0]["message"]["content"] or "").strip()
        except urllib.error.HTTPError as e:
            log("LLM", f"HTTP {e.code} {e.read()[:120]!r}")
        except Exception as e:
            log("LLM", f"失败 {e}")
        return ""


# ---------------------------------------------------------------- 动作

def read_title():
    return wxread.read_title()


def open_chat(name):
    """在左侧会话列表里找到名字匹配的那一行，直接点它。"""
    log("切换", f"在会话列表里找 {name}")
    try:
        rows = wxread.list_sessions()
    except Exception as e:
        log("切换", f"读会话列表失败 {e}")
        return read_title()
    want = name.replace(" ", "").lower()
    for x, y, text in rows:
        if want in text.replace(" ", "").lower():
            wxui.move_click(x, int(y))
            time.sleep(1.5)
            return read_title()
    log("切换", "列表里没有这个会话（可能需要先滚动）")
    return read_title()


def set_clipboard(text):
    subprocess.run("xclip -selection clipboard -i", shell=True,
                   input=text.encode(), env={"DISPLAY": wxread.DISP}, timeout=10)


def send(text):
    wxui.move_click(*wxread.regions()["input_xy"])
    time.sleep(0.3)
    wxui.press("ctrl_a")           # 清掉输入框里可能残留的内容
    set_clipboard(text)
    time.sleep(0.2)
    wxui.press("ctrl_v")
    time.sleep(0.6)
    wxui.press("enter")
    time.sleep(1.2)


# ---------------------------------------------------------------- 判定

JUDGE = """你是微信群里一个普通成员，判断"这条新消息值不值得我插一句话"。

不值得：广告/新闻推送/通知/系统消息、别人已经在聊得火热、我刚才才说过话。
值得：有人在提问、吐槽、抛梗、征求推荐。

只输出一行 JSON：
{"speak": true/false, "confidence": 0到1, "why": "10字内"}

最近聊天：
<<CTX>>

新消息（<<SIDE>>）：<<MSG>>"""


def sanitize(t, limit):
    t = re.sub(r"^(AI|助手|机器人)[:：]\s*", "", (t or "").strip())
    t = re.sub(r"[*_`#>]+", "", t).replace("\n", " ").strip().strip("\"'“”")
    if len(t) > limit:
        cut = max(t.rfind(p, 0, limit) for p in "。！？!?")
        t = t[:cut + 1] if cut > limit // 2 else t[:limit] + "…"
    return t.strip()


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.b = cfg["behavior"]
        self.llm = LLM(cfg["llm"])
        self.seen = {}
        self.last_reply_at = 0.0
        self.hour = []
        self.said = []

    def quiet(self):
        a, z = self.b["quiet_hours"]
        h = datetime.now().hour
        return (a <= h < z) if a <= z else (h >= a or h < z)

    def allowance(self):
        now = time.time()
        if self.quiet():
            return False, "静默时段"
        if now - self.last_reply_at < self.b["reply_cooldown_seconds"]:
            return False, "冷却中"
        self.hour = [t for t in self.hour if now - t < 3600]
        if len(self.hour) >= self.b["max_per_hour"]:
            return False, "这一小时说够了"
        return True, ""

    def judge(self, ctx, msg):
        out = self.llm.chat(
            [{"role": "user", "content": JUDGE.replace("<<CTX>>", ctx).replace("<<SIDE>>", msg["side"]).replace("<<MSG>>", msg["text"])}],
            model=self.cfg["llm"]["judge_model"], temperature=0.2, max_tokens=60)
        m = re.search(r"\{.*\}", out or "", re.S)
        if not m:
            return False, 0.0, "判官失联"
        try:
            d = json.loads(m.group(0))
            return bool(d.get("speak")), float(d.get("confidence") or 0), str(d.get("why") or "")
        except Exception:
            return False, 0.0, "判官说胡话"

    def reply(self, ctx, msg):
        prompt = (f"{self.cfg['persona']}\n\n群聊最近说了：\n{ctx}\n\n"
                  f"现在有人（{msg['side']}）说：{msg['text']}\n\n"
                  f"你就插一句话回他。只输出这句话本身，口语，不超过 {self.b['max_reply_chars']} 字，不要引号。")
        return sanitize(self.llm.chat([{"role": "user", "content": prompt}]), self.b["max_reply_chars"])

    def step(self):
        title = read_title()
        norm = lambda t: t.replace(" ", "").lower()
        if norm(self.cfg["target_chat"]) not in norm(title):
            log("注意", f"当前会话是「{title}」，不是目标「{self.cfg['target_chat']}」，尝试切换")
            title = open_chat(self.cfg["target_chat"])
            if norm(self.cfg["target_chat"]) not in norm(title):
                log("失败", f"切不过去（当前 {title}），本轮跳过")
                return

        msgs = wxread.read_chat()
        fresh = []
        for m in msgs:
            key = m["key"]
            if key not in self.seen:
                self.seen[key] = time.time()
                if m["side"] == "other":
                    fresh.append(m)

        if not fresh:
            return
        log("收到", f"{len(fresh)} 条新消息：" + " / ".join(m["text"][:24] for m in fresh))

        ok, why = self.allowance()
        if not ok:
            log("跳过", why)
            return

        ctx = "\n".join(f"{'我' if m['side']=='self' else '对方'}: {m['text']}"
                        for m in msgs[-self.b["context_size"]:])
        target = fresh[-1]
        speak, score, reason = self.judge(ctx, target)
        if not speak:
            log("跳过", f"判官不接（{reason} {score:.2f}）")
            return

        text = self.reply(ctx, target)
        if not text:
            log("跳过", "没生成出来")
            return

        if self.cfg["safety"]["dry_run"]:
            log("DRYRUN", f"本来会发：{text}")
        else:
            send(text)
            log("已发", text)
            self.last_reply_at = time.time()
            self.hour.append(self.last_reply_at)

    def run(self, once=False):
        log("启动", f"目标会话={self.cfg['target_chat']} 假跑={self.cfg['safety']['dry_run']} "
                    f"轮询={self.b['poll_seconds']}s")
        while True:
            try:
                self.step()
            except Exception as e:
                log("异常", repr(e))
            if once:
                break
            time.sleep(self.b["poll_seconds"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default=str(HERE / "config.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    cfg = load_cfg(a.config)
    if a.dry_run:
        cfg["safety"]["dry_run"] = True
    Bot(cfg).run(once=a.once)
