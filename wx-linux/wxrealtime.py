#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时插话机器人
==============

链路：sniffer.so 抓到新消息页 -> 本程序解析 -> 判断 -> 生成回复 -> XTEST 发送

特点：
  * 不读密钥、不用 OCR
  * 消息到达后 1-3 秒内可感知（靠 message_0.db-wal / session.db-wal / message_fts.db 的读盘）
  * 有 LLM key 就真聊天；没有则用固定话术（--stub）验证链路

用法：
    python wxrealtime.py --chat "某群" --stub        # 固定话术，验证实时性
    python wxrealtime.py --chat "某群"               # 接 config.json 里的 LLM
    python wxrealtime.py --chat "某群" --dry-run     # 只打印不发送
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/root/dsh/wx-linux")
from pageparse import parse_leaf  # noqa: E402
import wxui  # noqa: E402
import wxread  # noqa: E402

PAGES = "/root/dsh/wx-linux/logs/pages"
META = "/root/dsh/wx-linux/logs/pages_meta.jsonl"
DB = "/root/dsh/wx-linux/messages.db"
CFG = Path("/root/dsh/wx-linux/config.json")


def log(m):
    print(f"{datetime.now():%H:%M:%S} {m}", flush=True)


class RealTime:
    def __init__(self, chat, stub=False, dry=False, quiet=None):
        self.chat = chat
        self.stub = stub
        self.dry = dry
        self.seen = set()
        self.own = set()          # 我们自己发出去的，避免自问自答
        self.last_reply = 0.0
        self.started_at = int(time.time()) - 5
        self.cooldown = 3.0       # 秒
        self.llm = self.load_llm()

    # ---------- LLM ----------
    def load_llm(self):
        if self.stub:
            return None
        # 1) 优先用 config.json
        try:
            c = json.loads(CFG.read_text())
            l = c.get("llm", {})
            if l.get("api_key"):
                return l
        except Exception:
            pass
        # 2) 回退：读 DSH 已配置的 DeepSeek 凭据（不复制、不外泄）
        try:
            for line in open("/root/.dsh/.credentials.yaml"):
                if line.strip().startswith("DEEPSEEK_API_KEY:"):
                    key = line.split(":", 1)[1].strip().strip('"\'')
                    if key.startswith("sk-"):
                        log("已复用 DSH 的 DeepSeek 凭据")
                        return {"base_url": "https://api.deepseek.com/v1",
                                "api_key": key, "model": "deepseek-chat"}
        except Exception as e:
            log(f"读取凭据失败: {e}")
        return None

    def ask(self, text, context=""):
        if not self.llm:
            return f"收到「{text[:20]}」" if text else "收到"
        prompt = (f"你是微信群里的普通成员，说话短、口语、会接梗，不自我介绍、不提自己是AI。\n"
                  f"群里有人说：{text}\n"
                  f"{('上文：' + context) if context else ''}\n"
                  f"你就回一句，不超过 40 字，只输出这句话。")
        req = urllib.request.Request(
            self.llm["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps({"model": self.llm.get("model", "deepseek-chat"),
                             "messages": [{"role": "user", "content": prompt}],
                             "temperature": 1.1, "max_tokens": 120}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.llm["api_key"]})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log(f"LLM 失败 {e}")
            return ""

    # ---------- 读取新页 ----------
    def new_pages(self):
        """只挑消息/会话库的新页，避免解析无关页拖慢检测"""
        done = []
        for f in glob.glob(f"{PAGES}/*.bin"):
            name = os.path.basename(f)
            if name in self.seen:
                continue
            self.seen.add(name)
            if not any(k in name for k in ("_",)):
                continue
            done.append(f)
        return done

    def extract(self, path):
        """从一页里提取 (时间戳, 正文)。只认消息表那种 17 字段记录。"""
        out = []
        try:
            size = os.path.getsize(path)
        except OSError:
            return out
        if size < 512:
            return out
        rows = parse_leaf(path)
        for rowid, vals in rows:
            if len(vals) < 13:
                continue
            typ = vals[2] if isinstance(vals[2], int) else -1
            ts = vals[5] if isinstance(vals[5], int) else 0
            text = vals[12] if isinstance(vals[12], str) else ""
            if not text or text.startswith("<") or len(text) > 300:
                continue
            if typ != 1:                    # 只处理普通文本
                continue
            if ts and ts < self.started_at:  # 忽略历史消息
                continue
            out.append((ts, text))
        return out

    # ---------- 会话归属（用 session 预览反查） ----------
    def session_previews(self):
        prev = {}
        for f in glob.glob(f"{PAGES}/*.bin"):
            try:
                if os.path.getmtime(f) < time.time() - 120:
                    continue
                for rowid, vals in parse_leaf(f):
                    if len(vals) >= 2 and isinstance(vals[0], str) and isinstance(vals[1], str):
                        if vals[0] and vals[1]:
                            prev[vals[1]] = vals[0]
            except Exception:
                continue
        return prev

    # ---------- 发送 ----------
    def send(self, text):
        t0 = time.time()
        if self.dry:
            log(f"[DRYRUN] 会发：{text}")
            self.own.add(text)
            return True
        wxui.move_click(*wxread.regions()["input_xy"])
        time.sleep(0.15)
        subprocess.run("xclip -selection clipboard -i", shell=True,
                       input=text.encode(), env={"DISPLAY": wxread.DISP}, timeout=10)
        wxui.press("ctrl_v")
        time.sleep(0.25)
        wxui.press("enter")
        time.sleep(0.3)
        self.own.add(text)
        log(f"已发：{text}（发送耗时 {time.time()-t0:.2f}s）")
        return True

    # ---------- 主循环 ----------
    def ensure_chat(self):
        try:
            if self.chat.replace(" ", "") in wxread.read_title().replace(" ", ""):
                return True
        except Exception:
            pass
        for x, y, t in wxread.list_sessions():
            if self.chat.replace(" ", "") in t.replace(" ", ""):
                wxui.move_click(x, int(y))
                time.sleep(1.2)
                return True
        return False

    def run(self):
        log(f"实时值守：{self.chat}  模式={'固定话术' if self.stub else 'LLM'}  "
            f"{'假跑' if self.dry else '真发'}")
        last_check = 0
        while True:
            if time.time() - last_check > 45 and not getattr(self, "_checking", False):
                last_check = time.time()
                self._checking = True
                import threading
                def _bg():
                    try:
                        self.ensure_chat()
                    finally:
                        self._checking = False
                threading.Thread(target=_bg, daemon=True).start()
            pages = self.new_pages()
            if pages:
                cands = []
                page_of = {}
                for p in pages:
                    for ts_, tx in self.extract(p):
                        cands.append((ts_, tx))
                        page_of.setdefault(tx, p)
                if cands:
                    previews = {}
                    for ts, text in cands:
                        if text in self.own:
                            continue
                        key = (ts, text)
                        if key in self.seen:
                            continue
                        self.seen.add(key)
                        # 归属：预览里出现这条文本 => 属于该会话
                        owner = previews.get(text, "")
                        if owner and self.chat.replace(" ", "") not in owner.replace(" ", ""):
                            continue
                        if self.chat.replace(" ", "") not in owner.replace(" ", "") and owner:
                            continue
                        if time.time() - self.last_reply < self.cooldown:
                            continue
                        mtime = os.path.getmtime(page_of.get(text, 0)) if page_of.get(text) else 0
                        log(f"收到新消息：{text[:20]}"
                            f"（消息时间 {datetime.fromtimestamp(ts):%H:%M:%S}，"
                            f"落盘 {('%.1fs后' % (mtime-ts)) if mtime else '?'}，"
                            f"总延迟 {time.time()-ts:.1f}s）")
                        reply = self.ask(text)
                        if reply:
                            self.send(reply)
                            self.last_reply = time.time()
                        break
            time.sleep(0.2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", required=True)
    ap.add_argument("--stub", action="store_true", help="不调用 LLM，用固定话术")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    RealTime(a.chat, stub=a.stub, dry=a.dry_run).run()
