#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信实时聊天机器人（稳定版）
============================

链路：sniffer.so 捕获消息页 -> 解析 -> DeepSeek 生成 -> XTEST 发送 -> 回读校验

可靠性措施：
  * 状态落盘，重启不重复回复历史消息
  * 后台线程维持目标会话在前台
  * 发送后回读校验（自己的消息会再次出现在捕获页里），失败自动重试一次
  * 异常不退出，记录日志后继续
"""

import json
import os
import random
from collections import deque
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, "/root/dsh/wx-linux")
from pageparse import parse_leaf  # noqa: E402
import wxui  # noqa: E402
import wxread  # noqa: E402
import wxlog  # noqa: E402
import wxstage  # noqa: E402

PAGES = "/root/dsh/wx-linux/logs/pages"
META = "/root/dsh/wx-linux/logs/pages_meta.jsonl"
CFG = "/root/dsh/wx-linux/wbot.json"
STATE = "/root/dsh/wx-linux/logs/bot_state.json"
LOG = "/root/dsh/wx-linux/logs/bot.log"


def rotate_log():
    try:
        if os.path.getsize(LOG) > 5 * 1024 * 1024:
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass


def log(m):
    line = f"{datetime.now():%m-%d %H:%M:%S} {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


class Bot:
    def __init__(self):
        self.cfg = json.loads(open(CFG).read())
        self.chat = self.cfg["chat"]
        self.started = int(time.time()) - 10
        self.seen = set()
        self.sent = set()
        self.sent_norm = set()
        self.last_reply = 0.0
        self.meta_off = 0
        self.file_db = {}
        self.llm = self.load_llm()
        self.lock = threading.Lock()
        self.log = log
        self.wxlog = wxlog
        self.random = random
        self.recent = deque(maxlen=40)
        self.learned_names = set()            # 默认值，load_state 会覆盖
        self.names = {}                       # wxid -> 昵称
        self._names_ts = 0.0
        self.history = deque(maxlen=120)      # 全局最近上下文（role, text, sender）
        self.memory_summary = ""             # 压缩后的长期记忆
        self.conv = {}                       # 按人分开的对话记忆 {昵称: deque((role, text))}
        self.last_addressed_wxid = ""        # 最近一次回复的对象（话题接力用）
        self.last_addressed_ts = 0.0
        self.last_proactive = 0.0
        self.msg_since_judge = 0
        self.load_state()
        self.seed_from_log()

    # ---------- 状态 ----------
    def seed_from_log(self):
        """从历史日志里恢复自己说过的话，避免重启后自我回复"""
        try:
            with open(LOG) as f:
                for line in f:
                    m = re.search(r"(?:已发|发送状态未知)：(.*?)（", line)
                    if m:
                        self.sent_norm.add(self.norm(m.group(1)))
        except OSError:
            pass

    def load_state(self):
        try:
            st = json.loads(open(STATE).read())
            self.seen = set(st.get("seen", []))
            self.sent = set(st.get("sent", []))
            self.sent_norm = {self.norm(t) for t in self.sent}
            self.learned_names = set(st.get("learned_names", []))
            self.memory_summary = st.get("memory_summary", "")
            self.history = deque([tuple(e) if isinstance(e, list) else e
                                  for e in st.get("history", [])][-40:], maxlen=40)
            self.conv = {}
            for k, v in st.get("conv", {}).items():
                if isinstance(v, list):
                    self.conv[k] = deque([tuple(e) if isinstance(e, list) else e
                                          for e in v][-8:], maxlen=8)
        except Exception:
            pass

    @staticmethod
    def norm(t):
        return re.sub(r"[\s，。！？~～、,.!?]", "", t or "")

    @staticmethod
    def is_garbled(text):
        """判断是否乱码/二进制垃圾（控制字符、替换符过多）"""
        t = text or ""
        if not t:
            return True
        if any(ord(c) < 32 and c not in "\n\t" for c in t):
            return True
        if "\ufffd" in t:
            return True
        return False

    def save_state(self):
        try:
            tmp = STATE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"seen": list(self.seen)[-3000:],
                           "sent": list(self.sent)[-500:],
                           "learned_names": sorted(self.learned_names)[-50:],
                           "memory_summary": self.memory_summary,
                           "history": [list(e) for e in self.history],
                           "conv": {k: [list(e) for e in v] for k, v in self.conv.items()}}, f)
            os.replace(tmp, STATE)
        except OSError:
            pass

    # ---------- LLM ----------
    def load_llm(self):
        api_key = self.cfg.get("api_key", "")
        if not api_key:
            try:
                for line in open("/root/.dsh/.credentials.yaml"):
                    if line.strip().startswith("DEEPSEEK_API_KEY:"):
                        api_key = line.split(":", 1)[1].strip().strip("\"'")
                        break
            except OSError:
                pass
        if not api_key:
            log("没有可用的 LLM key")
            return None
        return {"key": api_key, "url": "https://api.deepseek.com/v1/chat/completions",
                "model": self.cfg.get("model", "deepseek-chat")}

    TRIGGERS = ("总结", "日报", "群报", "分析一下", "复盘")

    def on_demand_report(self, text):
        """触发式分析：生成报告并返回要回复的文字"""
        import glob as _glob
        before = set(_glob.glob("/root/dsh/wx-linux/reports/*.md"))
        try:
            subprocess.run(["/root/dsh/wx-linux/venv/bin/python", "-u",
                            "/root/dsh/wx-linux/wxanalyze.py",
                            "--once", "--today"],
                           capture_output=True, text=True, timeout=180)
        except Exception as e:
            log(f"触发分析失败: {e}")
            return ""
        after = set(_glob.glob("/root/dsh/wx-linux/reports/*.md"))
        new = sorted(after - before)
        if not new:
            return ""
        md = open(new[-1], encoding="utf-8").read()
        m = re.search(r"3[.、]\s*一句话概括\*{0,2}\s*\n+(.+)", md)
        one = (m.group(1).strip() if m else "总结好了")[:150]
        # 发完整海报（和网页版一致：话题+金句+概括+谁最活跃）
        poster = new[-1].replace(".md", ".png").replace("/reports/", "/reports/png/")
        if not os.path.exists(poster):
            try:
                import wxposter
                poster = wxposter.render(new[-1])
            except Exception as e:
                log(f"海报失败: {e}")
                poster = ""
        return (poster, one)

    def ask_raw(self, prompt, max_tokens=80, temperature=0.2):
        if not self.llm:
            return ""
        body = json.dumps({"model": self.llm["model"],
                           "messages": [{"role": "user", "content": prompt}],
                           "temperature": temperature,
                           "max_tokens": max_tokens}).encode()
        req = urllib.request.Request(
            self.llm["url"], data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.llm["key"]})
        try:
            with urllib.request.urlopen(req, timeout=60 if deep else 25) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log(f"判官调用失败: {e}")
            return ""

    JUDGE = (
        "你是微信群里的一个普通成员，判断「这条消息值不值得我主动插一句话」。\n"
        "默认倾向：不接（沉默永远比说错好）。\n\n"
        "必须接（speak=true）：有人 @ 我、点名问我、明显在接我的话。\n\n"
        "可以接（speak=true 且 confidence>=0.85）：\n"
        "- 日常闲聊、吐槽、抛梗、聊吃的玩的，我能自然接上\n"
        "- 常识/生活类问题，而且我确实有把握\n\n"
        "不要接（speak=false）：\n"
        "- 有人向全群提专业问题（技术配置、系统、政策、公司事务、具体数字/价格/费用）\n"
        "- 需要当事人或专业人士回答的问题\n"
        "- 我看不懂上下文，或不确定自己知道答案\n"
        "- 广告、通知、接龙、刷屏、单字、表情\n"
        "- 别人正在对话中，我插进去会打断\n\n"
        "只输出一行 JSON：{\"speak\": true/false, \"confidence\": 0到1, \"why\": \"10字内\"}\n\n"
        "最近群聊：\n<<CTX>>\n\n新消息：<<MSG>>")

    def judge(self, text):
        ctx = "\n".join(f"群友: {t}" for _, t in list(self.recent)[-8:])
        prompt = (self.JUDGE.replace("<<CTX>>", ctx).replace("<<MSG>>", text[:200]))
        out = self.ask_raw(prompt)
        m = re.search(r"\{.*\}", out or "", re.S)
        if not m:
            return False, 0.0, "判官失联"
        try:
            d = json.loads(m.group(0))
            return bool(d.get("speak")), float(d.get("confidence") or 0), str(d.get("why") or "")
        except Exception:
            return False, 0.0, "判官说胡话"

    def latest_report_summary(self, n=600):
        """取最新一份群分析报告，作为长期背景"""
        try:
            import glob
            files = sorted(glob.glob("/root/dsh/wx-linux/reports/*.md"), reverse=True)
            if files:
                txt = open(files[0], errors="replace").read()
                # 去掉标题行，保留正文
                body = "\n".join(txt.splitlines()[5:]).strip()
                return body[:n]
        except Exception:
            pass
        return ""

    def build_context(self, sender_name=""):
        parts = []
        rep = self.latest_report_summary()
        if rep:
            parts.append(f"[最近的群聊分析] {rep}")
        if self.memory_summary:
            parts.append(f"[背景] {self.memory_summary}")
        # 跟当前这个人最近的来回（按人记忆）
        if sender_name:
            c = self.conv.get(sender_name)
            if c:
                parts.append(f"[和 {sender_name} 最近的对话]")
                for role, txt in list(c)[-10:]:
                    who = "我" if role == "assistant" else sender_name
                    parts.append(f"{who}: {txt[:60]}")
        # 群聊最近动态（简短，给整体氛围）
        recent = [e for e in list(self.history)[-20:] if isinstance(e, (tuple, list)) and len(e) >= 2]
        if recent:
            parts.append("[群聊最近]")
            for e in recent:
                role, txt = e[0], e[1]
                sender = e[2] if len(e) >= 3 else ""
                who = "我" if role == "assistant" else (sender or "群友")
                parts.append(f"{who}: {txt[:80]}")
        return "\n".join(parts)

    def compress_history(self):
        """历史超过阈值时，把旧部分压缩成背景记忆"""
        if len(self.history) < 30:
            return
        old = list(self.history)[:-10]
        keep = list(self.history)[-10:]
        blob = "\n".join(f"{(s or '群友')}: {t[:40]}" for _, t, s in old)
        summary = self.ask_raw(f"把下面这段群聊压成 2~3 句背景摘要：\n{blob}",
                               max_tokens=150, temperature=0.3)
        if summary:
            self.memory_summary = (self.memory_summary + " " + summary).strip()[-600:]
        self.history = deque(keep, maxlen=120)

    def resolve_name(self, sender):
        if not sender:
            return ""
        if time.time() - self._names_ts > 300:
            try:
                import wxnames
                self.names = wxnames.load()
                self._names_ts = time.time()
            except Exception:
                pass
        return self.names.get(sender, "")

    def split_reply(self, text):
        """按句子拆成 1~N 条气泡；整句不截断"""
        raw = (text or "").strip()
        if not raw:
            return []
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        # 结构化块（==标题== 模板 / 键值对）整块发，不拆
        if len(lines) >= 3 and (
                any(re.match(r"^==.+==$", l) for l in lines)
                or sum(1 for l in lines if "：" in l or ": " in l) >= len(lines) * 0.6):
            return [raw]
        joined = "".join(lines)
        # 按句子边界切，标点保留
        sents = re.findall(r"[^。！？!?~～\n]+[。！？!?~～]*", joined)
        sents = [x.strip() for x in sents if x.strip()]
        if not sents:
            return [raw]
        cap = max(1, int(self.cfg.get("max_reply_messages", 3)))
        if len(sents) <= cap:
            return sents
        # 句数超过上限：按顺序合并成 cap 条，保证每句完整
        per = -(-len(sents) // cap)
        out = ["".join(sents[i:i + per]) for i in range(0, len(sents), per)]
        return [o for o in out if o][:cap]

    SUMMARY_KEYS = ("新闻", "热点", "热搜", "头条", "时事", "总结", "盘点", "汇总",
                    "说说今天", "今天发生", "最近发生")

    def ask(self, text, sender="", deep=False):
        if not self.llm:
            return ""
        summary = any(k in (text or "") for k in self.SUMMARY_KEYS)
        ctx_text = self.build_context(self.resolve_name(sender))
        sname = self.resolve_name(sender)
        who = f"（昵称 {sname}）" if sname else ""
        now = datetime.now()
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
        now_str = f"{now.strftime('%Y-%m-%d %H:%M')} {weekday}"
        news = ""
        try:
            import wxnews
            news = wxnews.fetch_for(text)
        except Exception:
            pass
        if summary:
            length_rule = (
                "这是总结/盘点类问题：把上面实时信息里的**主要条目都覆盖到**，"
                "每条一句话说清楚，不要漏、不要截断、不要编造；篇幅按条目数量自然来。\n"
            )
        else:
            length_rule = (
                "长度按内容来，把话说完整，不要为了字数截断句子；也别啰嗦凑字。"
                "可以分 1~3 句自然的短句（会拆成几条发）。\n"
            )
        prompt = (f"现在是 {now_str}。\n"
                  + (f"以下是联网查到的实时信息，回答相关问题时以它为准：\n{news}\n" if news else "")
                  + f"{self.cfg['persona']}\n\n"
                  + (f"对话背景（延续当前话题，别当第一次聊天）：\n{ctx_text}\n\n" if ctx_text else "")
                  + f"对方{who}刚说：{text}\n"
                  + length_rule
                  + "只输出消息本身，别用序号别用引号。\n"
                  + "【硬规则】\n"
                  + "- 国内政治敏感话题（领导人、党派、涉疆涉藏涉港台独、历史事件、体制批评）：一律不接，只输出 [SKIP]。\n"
                  + "- 国外政治（美国大选、国际冲突、外国政要）可以正常讨论，但保持中立、不站队、不吹不黑。\n"
                  + "- 色情、赌博、毒品、暴力：一律不接，只输出 [SKIP]。\n"
                  + "如果这条消息需要专业判断、内部信息、具体数字，或你不确定答案：只输出 [SKIP]，不要编造、不要猜。\n"
                  + "重要：如果对方要求按特定格式输出（模板、==标题==、表格、键值对、指定字段），严格照原格式输出，不要用自己的话转述。")
        use_model = self.llm["model"]
        max_tok = 400
        if deep and self.cfg.get("deep_on_mention"):
            use_model = self.cfg.get("deep_model", use_model)
            max_tok = 1500          # 推理模型要留够思考空间
        if summary:
            max_tok = max(max_tok, 600)
        body = json.dumps({"model": use_model,
                           "messages": [{"role": "user", "content": prompt}],
                           "temperature": 0.9, "max_tokens": max_tok}).encode()
        req = urllib.request.Request(
            self.llm["url"], data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.llm["key"]})
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=60 if deep else 25) as r:
                    t = json.loads(r.read())["choices"][0]["message"]["content"].strip()
                return t.strip()
            except Exception as e:
                log(f"LLM 第{attempt+1}次失败: {e}")
                last_err = e
                time.sleep(1)
        # 两次都失败 → 飞书告警（限流 1 小时，防刷屏）
        try:
            import larkalert
            hint = "余额不足/限流" if "402" in str(last_err) else "网络或服务异常"
            larkalert.send(f"⚠️ 微信机器人 LLM 连续失败（疑似 {hint}）。\n错误：{str(last_err)[:80]}",
                           key="llm_fail", cooldown=3600)
        except Exception:
            pass
        return ""

    # ---------- 消息读取 ----------
    def read_meta(self):
        try:
            with open(META) as f:
                f.seek(self.meta_off)
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "file" in r:
                        self.file_db[r["file"]] = r.get("db", "")
                self.meta_off = f.tell()
        except OSError:
            pass

    def scan(self):
        """返回新出现的消息 (ts, text, sender)。优先读主表，再用搜索索引兜底"""
        self.read_meta()
        out = []
        try:
            names = os.listdir(PAGES)
        except OSError:
            return out

        seen_round = set()   # 本轮已收集的 (ts, text)，避免主表/索引重复
        PLACEHOLDER = re.compile(
            r"\[(图片|语音|表情|文件|链接|视频|动画|位置|名片|转账|红包|小程序|音乐|聊天记录|引用|笔记)\]")

        # 先主表（含发送者），再搜索索引（无发送者，但可靠）
        for dbkey in ("message_0.db", "message_fts.db"):
            for n in names:
                if n in self.seen:
                    continue
                db = self.file_db.get(n, "")
                if not db.endswith(dbkey):   # 精确匹配，排除 .db-wal / .db-shm（帧头会导致乱码）
                    continue
                self.seen.add(n)
                p = os.path.join(PAGES, n)
                try:
                    rows = parse_leaf(p)
                except Exception:
                    continue
                for _, vals in rows:
                    if dbkey == "message_0.db":
                        if len(vals) < 13 or vals[2] != 1:
                            continue
                        ts = vals[5] if isinstance(vals[5], int) else 0
                        raw = vals[12] if isinstance(vals[12], str) else ""
                        m = re.match(r"^([A-Za-z0-9_\-\.]{4,64}):\s*\n(.+)$", raw, re.S)
                        if m:
                            sender, text = m.group(1), m.group(2).strip()
                        else:
                            sender, text = "", raw
                    else:  # message_fts.db 搜索索引：正文在 [1]，秒级时间在 [7]
                        if len(vals) < 8:
                            continue
                        text = vals[1] if isinstance(vals[1], str) else ""
                        ts = vals[7] if isinstance(vals[7], int) else 0
                        sender = ""   # 索引不含发送者
                    if not text or text.startswith("<") or len(text) > 500:
                        continue
                    if self.is_garbled(text):
                        continue
                    if PLACEHOLDER.fullmatch(text.strip()):
                        continue
                    if not text:
                        continue
                    if not ts or ts < self.started:
                        continue
                    key = (ts, text)
                    if key in seen_round:
                        continue
                    seen_round.add(key)
                    out.append((ts, text, sender))
        return out

    # ---------- 发送 ----------
    def input_has_text(self):
        """输入框里是否还有内容（有内容=没发出去）"""
        try:
            from PIL import Image
            x, y, w, h = wxread.geom()
            box = (x + int(0.44 * w), y + int(0.885 * h), x + int(0.80 * w), y + int(0.945 * h))
            img = Image.open(wxread.shot()).crop(box).convert("L")
            dark = sum(1 for px in img.getdata() if px < 120)
            return dark > 120
        except Exception:
            return True

    def send_image(self, path):
        """把图片贴进输入框发送"""
        t0 = time.time()
        try:
            wxui.move_click(*wxread.regions()["input_xy"])
            time.sleep(0.1)
            subprocess.run(f"xclip -selection clipboard -t image/png -i '{path}'",
                           shell=True, env={"DISPLAY": wxread.DISP}, timeout=15)
            time.sleep(0.3)
            wxui.press("ctrl_v")
            time.sleep(1.4)
            wxui.press("enter")
            time.sleep(0.6)
            log(f"已发图片：{os.path.basename(path)}（{time.time()-t0:.1f}s）")
            return True
        except Exception as e:
            log(f"发图失败: {e}")
            return False

    def _header_sig(self):
        """取聊天区标题栏的灰度缩略图，用于快速比对（毫秒级）"""
        try:
            from PIL import Image
            x, y, w, h = wxread.geom()
            box = (x + int(0.38 * w), y + int(0.055 * h), x + int(0.80 * w), y + int(0.105 * h))
            img = Image.open(wxread.shot()).crop(box).convert("L").resize((64, 12))
            return list(img.getdata())
        except Exception:
            return None

    def _same_target(self, sig):
        base = getattr(self, "_header_base", None)
        if not sig or not base:
            return False
        try:
            diff = sum(abs(a - b) for a, b in zip(sig, base)) / len(sig)
            return diff < 18
        except Exception:
            return False

    def ensure_target(self):
        """发送前确认在目标会话：先毫米级像素比对，不匹配才 OCR"""
        now = time.time()
        if now - getattr(self, "_target_ok_until", 0) < 120:
            return True
        sig = self._header_sig()
        if self._same_target(sig):
            self._target_ok_until = now
            return True
        try:
            cur = wxread.read_title()
        except Exception:
            cur = ""
        if self.chat.replace(" ", "") in cur.replace(" ", ""):
            self._target_ok_until = now
            self._header_base = sig
            return True
        for _ in range(2):
            for x, y, t in wxread.list_sessions():
                if self.chat.replace(" ", "") in t.replace(" ", ""):
                    wxui.move_click(x, int(y))
                    time.sleep(1.5)
                    cur = wxread.read_title()
                    if self.chat.replace(" ", "") in cur.replace(" ", ""):
                        self._target_ok_until = time.time()
                        self._header_base = self._header_sig()
                        return True
            time.sleep(1)
        log(f"当前会话不是目标（{cur}），放弃发送")
        return False

    def send(self, text):
        t0 = time.time()
        if not self.ensure_target():
            return False
        # 先登记，避免把自己发出的消息当成新消息（也避免重复）
        self.sent.add(text)
        self.sent_norm.add(self.norm(text))
        is_multi = "\n" in text
        try:
            wxui.move_click(*wxread.regions()["input_xy"])
            time.sleep(0.1)
            subprocess.run("xclip -selection clipboard -i", shell=True,
                           input=text.encode(), env={"DISPLAY": wxread.DISP}, timeout=10)
            wxui.press("ctrl_v")
            time.sleep(0.15)
            wxui.press("enter")
            time.sleep(0.8 if is_multi else 0.3)
        except Exception as e:
            log(f"发送异常: {e}")
            return False
        self._last_send_ms = int((time.time() - t0) * 1000)
        # 多行消息清空输入框更慢，确认失败时重试几次，避免"状态未知"误报
        ok = not self.input_has_text()
        if not ok:
            for _ in range(3):
                time.sleep(0.6)
                if not self.input_has_text():
                    ok = True
                    break
        log(f"{'已发' if ok else '发送状态未知'}：{text[:30]}（{time.time()-t0:.1f}s）")
        return True

    def wait_echo(self, text, timeout):
        deadline = time.time() + timeout
        key = text.strip()[:20]
        while time.time() < deadline:
            for _, tx, _ in self.scan():
                if key and key in tx:
                    return True
            time.sleep(0.3)
        return False

    # ---------- 会话保持 ----------
    def locked(self):
        """检测微信是否处于锁屏状态"""
        try:
            rows = wxread.ocr(wxread.shot(), wxread.regions()["chat"])
            txt = " ".join(t for _, _, t, sc in rows if sc > 0.5).lower()
            return "locked" in txt or "lock to continue" in txt or "验证" in txt
        except Exception:
            return False

    def backfill(self):
        """兜底：会话预览里出现没处理过的最后一条消息，就补处理"""
        handled = set()
        while True:
            time.sleep(60)
            try:
                rows = wxread.list_sessions()
                for i, (x, y, t) in enumerate(rows):
                    if self.chat.replace(" ", "") not in t.replace(" ", ""):
                        continue
                    cands = []
                    for x2, y2, t2 in rows[i + 1:i + 4]:
                        if 0 < y2 - y < 90:
                            cands.append(t2)
                    preview = ""
                    for t2 in cands:
                        if re.fullmatch(r"\d{1,2}:\d{2}", t2.strip()):
                            continue
                        if t2.strip() in ("昨天", "前天", "星期六", "星期日",
                                          "星期一", "星期二", "星期三", "星期四", "星期五"):
                            continue
                        if len(t2.strip()) > len(preview.strip()):
                            preview = t2
                    if not preview:
                        preview = max(cands, key=len) if cands else ""
                    if not preview or len(preview.strip()) < 2:
                        break
                    key = self.norm(preview)
                    if key in self.sent_norm or key in handled:
                        break
                    handled.add(key)
                    log(f"兜底发现未处理消息：{preview[:30]}")
                    reply = self.ask(preview)
                    if reply and time.time() - self.last_reply >= self.cfg["cooldown_seconds"]:
                        self.send(reply)
                        self.last_reply = time.time()
                        self.save_state()
                    break
            except Exception as e:
                log(f"兜底异常: {e!r}")

    def keeper(self):
        while True:
            try:
                try:
                    wxui.focus_wechat()      # 保持焦点，微信读盘更及时
                except Exception:
                    pass
                try:
                    g = wxread.geom()
                except Exception:
                    g = (0, 0, 0, 0)
                if g[2] < 500:
                    if time.time() - getattr(self, "_login_logged", 0) > 300:
                        log("⚠️ 微信处于登录界面，需要扫码 + 手机确认")
                        self._login_logged = time.time()
                    time.sleep(45)
                    continue
                cur = ""
                for _ in range(3):                    # OCR 偶发读空，重试三次
                    try:
                        cur = wxread.read_title()
                    except Exception:
                        cur = ""
                    if cur.strip():
                        break
                    time.sleep(1.2)
                if not cur.strip():
                    # 注意：不要 kill WeChatAppEx —— 会导致微信输入链路失效
                    log("连续三次读不到标题，稍后重试")
                    time.sleep(3)
                    cur = wxread.read_title()
                if self.chat.replace(" ", "") not in cur.replace(" ", ""):
                    log(f"会话不在目标（当前 {cur}），切回")
                    for x, y, t in wxread.list_sessions():
                        if self.chat.replace(" ", "") in t.replace(" ", ""):
                            wxui.move_click(x, int(y))
                            time.sleep(1.5)
                            break
            except Exception as e:
                log(f"保活异常: {e}")
            time.sleep(20)

    # ---------- 主循环 ----------
    def run(self):
        log(f"启动：会话={self.chat} 模型={self.llm['model'] if self.llm else '无'}")
        threading.Thread(target=self.keeper, daemon=True).start()
        # 兜底扫描已停用：OCR 无法可靠区分"会话名"和"消息预览"，误判会污染群聊
        # threading.Thread(target=self.backfill, daemon=True).start()
        while True:
            try:
                for ts, text, sender in self.scan():
                    wxstage.run(self, text, ts, sender=sender)
            except Exception as e:
                log(f"主循环异常: {e!r}")
                wxlog.event("error", detail=repr(e)[:200])
            time.sleep(0.2)


def acquire_lock():
    """单实例保护：拿不到锁就退出，避免两个进程同时回话"""
    import fcntl
    f = open("/root/dsh/wx-linux/logs/bot.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("已有实例在运行，退出")
        sys.exit(0)
    return f


if __name__ == "__main__":
    os.makedirs("/root/dsh/wx-linux/logs", exist_ok=True)
    _lock = acquire_lock()
    rotate_log()
    Bot().run()
