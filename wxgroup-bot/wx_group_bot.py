#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信群 AI 插话机器人
====================

读本地数据库拿全群消息 + UIA 模拟键盘发送，不注入微信进程。

链路：
    群消息 -> Listener 轮询 -> 触发判定 -> 拼上下文 -> LLM -> 清洗 -> 发送 -> 冷却

两种运行模式：
    假跑（推荐先跑这个，不碰微信）：  python wx_group_bot.py --offline --dry-run --mock mock_chat.txt
    真跑：                            python wx_group_bot.py

依赖（只在真跑时需要）：
    pip install wechatauto-replica

作者注：所有与微信库的交互都收敛在 WeChatBackend 里。
        如果你的 wechatauto 版本接口名不同，只改那一个类即可，上层逻辑不用动。
"""

from __future__ import annotations

import argparse
import json
import queue
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------------------------------------------------------------- 默认配置

DEFAULT_CONFIG = {
    "group": "改成你的群名（要和微信里显示的完全一致）",
    "persona": (
        "你是这个微信群里的一员，不是客服，也不是助手。"
        "说话短、口语、有点损但不刻薄，会接梗，不懂的会直接说不懂。"
        "从不自我介绍，从不提自己是 AI 或机器人，不说'作为AI'这类话。"
    ),
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "填你的 key",
        "model": "deepseek-chat",
        "judge_model": "deepseek-chat",
        "temperature": 1.15,
        "max_tokens": 160,
    },
    "behavior": {
        "at_reply": True,          # 被 @ 或点名必回
        "my_names": [],            # 群里叫你的名字/外号，被提到就算点名
        "sample_every": 10,        # 每来 N 条消息抽一条判断要不要插话
        "speak_probability": 0.6,  # 判官说该说时，再说出口的概率（降频率，更像人）
        "judge_threshold": 0.6,    # 判官置信度门槛
        "cooldown_seconds": 150,   # 两次主动插话最小间隔
        "at_cooldown_seconds": 4,  # 被点名后的最小间隔
        "max_per_hour": 8,
        "quiet_hours": [0, 8],     # 这个区间不外发（左闭右开，24 点写 0）
        "context_size": 25,        # 喂给模型的历史条数
        "max_reply_chars": 60,
        "reply_parts": 2,          # 一条回复最多拆几条发
        "part_gap_seconds": 1.6,   # 拆条之间的停顿
    },
    "safety": {
        "dry_run": True,           # 只打印不发送
        "ignore_senders": [],      # 不理会这些人（昵称）
        "owner_wxid": "",          # 允许用 /pause /resume 控制机器人的 wxid
        "keywords": [],            # 只在这些关键词出现时才考虑插话（留空=不限）
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path) -> dict:
    if not path.exists():
        print(f"[配置] 没找到 {path}，先复制一份：cp config.example.json config.json")
        sys.exit(2)
    with path.open("r", encoding="utf-8") as f:
        return deep_merge(DEFAULT_CONFIG, json.load(f))


# ---------------------------------------------------------------- 日志

_print_lock = threading.Lock()


def log(tag: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    with _print_lock:
        try:
            print(f"{ts} [{tag}] {msg}", flush=True)
        except UnicodeEncodeError:
            # Windows GBK 控制台兜底
            enc = (sys.stdout.encoding or "utf-8")
            print(f"{ts} [{tag}] {msg.encode(enc, 'replace').decode(enc)}", flush=True)


# ---------------------------------------------------------------- 消息归一化

def field(obj, *names, default=""):
    """同时兼容 dict 和对象两种消息形态，以及不同版本的字段名。"""
    for n in names:
        try:
            if isinstance(obj, dict):
                if n in obj and obj[n] not in (None, ""):
                    return obj[n]
            else:
                v = getattr(obj, n, None)
                if v not in (None, ""):
                    return v
        except Exception:
            continue
    return default


class Msg:
    __slots__ = ("id", "sender", "text", "is_self", "raw")

    def __init__(self, id, sender, text, is_self, raw):
        self.id = id
        self.sender = sender
        self.text = text
        self.is_self = is_self
        self.raw = raw

    def __repr__(self):
        return f"<{self.sender}: {self.text[:20]}>"


def normalize(raw, my_names: list[str]) -> Msg | None:
    mid = str(field(raw, "id", "message_id", "local_id", default=""))
    sender = str(field(raw, "sender_remark", "sender_name", "sender", "sender_wxid", default="?"))
    text = field(raw, "content", "text", default="")
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    text = str(text or "").strip()
    if not text:
        return None

    # 非文本消息在库里是一大段 XML/占位符，直接丢掉
    if text.startswith("<") or text in ("[图片]", "[语音]", "[视频]", "[文件]", "[动画表情]"):
        return None

    attr = str(field(raw, "attr", "direction", default="")).lower()
    is_self = attr in ("self", "sent", "out") or sender in my_names
    return Msg(mid, sender, text, is_self, raw)


# ---------------------------------------------------------------- LLM

class LLM:
    def __init__(self, cfg: dict, offline: bool = False):
        self.cfg = cfg
        self.offline = offline

    def chat(self, messages: list[dict], model: str | None = None,
             temperature: float | None = None, max_tokens: int | None = None) -> str:
        if self.offline:
            return self._offline_reply(messages)

        c = self.cfg
        body = {
            "model": model or c["model"],
            "messages": messages,
            "temperature": c["temperature"] if temperature is None else temperature,
            "max_tokens": max_tokens or c["max_tokens"],
        }
        req = urllib.request.Request(
            c["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + c["api_key"],
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.loads(r.read().decode("utf-8"))
            return (data["choices"][0]["message"]["content"] or "").strip()
        except urllib.error.HTTPError as e:
            log("LLM", f"HTTP {e.code}: {e.read()[:200]!r}")
        except Exception as e:
            log("LLM", f"调用失败: {e}")
        return ""

    @staticmethod
    def _offline_reply(messages: list[dict]) -> str:
        last = messages[-1]["content"] if messages else ""
        pool = ["啊这", "确实", "我不同意", "然后呢", "别急，让我想想", "哈哈哈哈哈算你赢"]
        if "值得" in last or "judge" in last:
            return json.dumps({"speak": random.random() < 0.5, "confidence": 0.8, "why": "offline"})
        return random.choice(pool)


JUDGE_PROMPT = """你是微信群里一个普通成员，正在决定"这条消息值不值得我插一句嘴"。

判断标准（重要）：
- 有人提问、求推荐、吐槽、晒东西、抛梗 —— 值得接
- 寒暄、通知、接龙、表情包刷屏、别人已经在聊得热火朝天 —— 不值得插
- 广告、链接、文件、系统消息 —— 不值得
- 你自己刚说过话 —— 不值得

只输出一行 JSON，不要别的：
{"speak": true 或 false, "confidence": 0到1的小数, "why": "不超过10个字"}

群聊最近消息：
<<CONTEXT>>

现在这条新消息（<<SENDER>>）：<<TEXT>>
"""


# ---------------------------------------------------------------- 频率控制

class Budget:
    def __init__(self, cfg: dict):
        self.c = cfg
        self.last_proactive = 0.0
        self.last_at = 0.0
        self.hour_marks: deque[float] = deque()

    def _quiet(self, now: float) -> bool:
        q = self.c["quiet_hours"]
        if not q or len(q) != 2:
            return False
        start, end = q
        h = datetime.fromtimestamp(now).hour
        if start <= end:
            return start <= h < end
        return h >= start or h < end

    def allow(self, now: float, kind: str) -> tuple[bool, str]:
        c = self.c
        if self._quiet(now):
            return False, "静默时段"
        if kind == "at":
            if now - self.last_at < c["at_cooldown_seconds"]:
                return False, "被点名冷却中"
        else:
            if now - self.last_proactive < c["cooldown_seconds"]:
                return False, f"还差 {int(c['cooldown_seconds'] - (now - self.last_proactive))}s 冷却"
        while self.hour_marks and now - self.hour_marks[0] > 3600:
            self.hour_marks.popleft()
        if len(self.hour_marks) >= c["max_per_hour"]:
            return False, "这一小时说太多了"
        return True, ""

    def mark(self, now: float, kind: str) -> None:
        self.hour_marks.append(now)
        if kind == "at":
            self.last_at = now
        else:
            self.last_proactive = now


# ---------------------------------------------------------------- 输出清洗

_MD = re.compile(r"(\*\*|__|`{1,3}|^#+\s*|^\s*[-*]\s+)", re.M)


def sanitize(text: str, max_chars: int) -> str:
    if not text:
        return ""
    t = _MD.sub("", text)
    t = t.replace("```", "")
    t = re.sub(r"^\s*(AI|助手|机器人|小编)[:：]\s*", "", t)
    t = t.replace("\n", " ")
    t = re.sub(r"\s{2,}", " ", t).strip()
    t = t.strip("\"'“”‘’")
    if len(t) > max_chars:
        cut = max(t.rfind(p, 0, max_chars) for p in "。！？!?")
        t = t[:cut + 1] if cut > max_chars // 2 else t[:max_chars].rstrip() + "…"
    return t.strip()


def split_parts(text: str, limit: int) -> list[str]:
    """按句拆成最多 limit 条，宁可少发也不要把一句话劈两半。"""
    parts = [p for p in re.split(r"(?<=[。！？!?~～])", text) if p.strip()]
    if len(parts) <= limit:
        return [p.strip() for p in parts if p.strip()] or [text]
    return [text]


# ---------------------------------------------------------------- 微信后端

class WeChatBackend:
    """真跑：wechatauto-replica（微信 4.x，读库 + UIA 发送，不注入进程）。

    如果你的库里 API 名字不一样，改 start / send 两个方法就够了：
        wx.AddListenChat(who=群名, callback=回调)   -> 换成你的注册监听方式
        wx.SendMsg(text, who=群名)                  -> 换成你的发送方式
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.wx = None
        self._stop = threading.Event()

    def start(self, on_message) -> None:
        try:
            from wechatauto import WeChat  # type: ignore
        except ImportError:
            log("启动", "缺少依赖，先执行： pip install wechatauto-replica")
            sys.exit(2)

        log("启动", "正在连接微信（需要微信 4.1.12+ 已登录、窗口不要最小化）…")
        self.wx = WeChat()

        def _cb(raw, *_args, **_kw):
            try:
                on_message(raw)
            except Exception as e:  # 回调里绝不能抛，否则监听线程会挂
                log("回调", f"处理异常: {e}")

        group = self.cfg["group"]
        try:
            self.wx.AddListenChat(who=group, callback=_cb)
        except Exception as e:
            log("启动", f"注册监听失败: {e}")
            log("启动", "检查：群名是否完全一致、微信是否在前台、先跑一次 `wechatauto 体检`")
            raise
        log("启动", f"已监听群：{group}")

    def send(self, text: str) -> bool:
        if self.wx is None:
            return False
        try:
            self.wx.SendMsg(text, who=self.cfg["group"])
            return True
        except TypeError:
            try:
                self.wx.SendMsg(msg=text, who=self.cfg["group"])
                return True
            except Exception as e:
                log("发送", f"失败: {e}")
        except Exception as e:
            log("发送", f"失败: {e}")
        return False

    def stop(self) -> None:
        self._stop.set()


class MockBackend:
    """假跑：从文本文件里逐行喂消息，用来验证逻辑而不碰微信。"""

    def __init__(self, script: Path, interval: float = 1.2):
        self.script = script
        self.interval = interval
        self._t = None

    def start(self, on_message) -> None:
        def run():
            if not self.script.exists():
                log("Mock", f"没找到剧本文件 {self.script}")
                return
            for line in self.script.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    sender, text = line.split(":", 1)
                else:
                    sender, text = "路人", line
                time.sleep(self.interval)
                log("Mock", f"{sender.strip()}: {text.strip()}")
                on_message({"id": f"m{time.time()}", "sender": sender.strip(),
                            "content": text.strip(), "attr": "friend"})
            log("Mock", "剧本演完了，按 Ctrl+C 退出")

        self._t = threading.Thread(target=run, daemon=True, name="mock")
        self._t.start()

    def send(self, text: str) -> bool:
        log("MockSend", text)
        return True

    def stop(self) -> None:
        pass


# ---------------------------------------------------------------- 机器人

class GroupBot:
    def __init__(self, cfg: dict, backend, llm: LLM):
        self.cfg = cfg
        self.b = cfg["behavior"]
        self.s = cfg["safety"]
        self.persona = cfg["persona"]
        self.backend = backend
        self.llm = llm

        self.history: deque[Msg] = deque(maxlen=max(60, self.b["context_size"] * 3))
        self.seen: deque[str] = deque(maxlen=800)
        self.budget = Budget(self.b)
        self.paused = False
        self.msg_count = 0
        self.q: queue.Queue[Msg] = queue.Queue()
        self._worker = threading.Thread(target=self._loop, daemon=True, name="brain")

    # ---- 生命周期
    def start(self) -> None:
        self._worker.start()
        self.backend.start(self._on_message)
        log("运行", "在跑。Ctrl+C 退出。")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            log("退出", "收到中断，收尾中")
            self.backend.stop()

    # ---- 收消息（必须极快返回，重活丢队列）
    def _on_message(self, raw) -> None:
        my_names = list(self.b.get("my_names") or [])
        m = normalize(raw, my_names)
        if m is None:
            return
        if m.id and m.id in self.seen:
            return
        if m.id:
            self.seen.append(m.id)

        self.history.append(m)
        if m.is_self:
            return
        if m.sender in (self.s.get("ignore_senders") or []):
            return

        self.msg_count += 1
        self.q.put(m)

    # ---- 决策线程
    def _loop(self) -> None:
        while True:
            m = self.q.get()
            try:
                self._handle(m)
            except Exception as e:
                log("异常", f"{e}")

    def _handle(self, m: Msg) -> None:
        now = time.time()

        # 主人控制指令
        if self._control(m):
            return
        if self.paused:
            return

        kind = None
        if self._is_called(m):
            kind = "at"
        elif self.msg_count % max(1, self.b["sample_every"]) == 0:
            kind = "proactive"

        if kind is None:
            return

        ok, why = self.budget.allow(now, kind)
        if not ok:
            log("跳过", f"{why}")
            return

        if kind == "proactive":
            kw = self.s.get("keywords") or []
            if kw and not any(k in m.text for k in kw):
                log("跳过", "不含关键词")
                return
            speak, score, reason = self._judge(m)
            if not speak or score < self.b["judge_threshold"]:
                log("跳过", f"判官不接（{reason} {score:.2f}）")
                return
            if random.random() > self.b["speak_probability"]:
                log("跳过", "掷骰子没过（保持自然）")
                return
            log("插话", f"判官通过（{reason} {score:.2f}）")
        else:
            log("被点名", f"{m.sender}: {m.text[:30]}")

        reply = self._generate(m)
        if not reply:
            return
        self._deliver(reply, now, kind)

    # ---- 控制
    def _control(self, m: Msg) -> bool:
        owner = self.s.get("owner_wxid") or ""
        if owner and m.sender != owner:
            return False
        cmd = m.text.strip().lower()
        if cmd == "/pause":
            self.paused = True
            self.backend.send("（我先闭嘴）")
            log("控制", "已暂停")
            return True
        if cmd == "/resume":
            self.paused = False
            self.backend.send("（我回来了）")
            log("控制", "已恢复")
            return True
        return False

    # ---- 触发判定
    def _is_called(self, m: Msg) -> bool:
        if not self.b["at_reply"]:
            return False
        text = m.text
        names = list(self.b.get("my_names") or [])
        if names and any(n and n in text for n in names):
            return True
        # 库里 @ 通常会在正文里留 @昵称
        if "@" in text and names and any(n in text.split("@")[-1][:12] for n in names):
            return True
        return False

    # ---- 上下文
    def _context(self, n: int) -> str:
        lines = []
        for h in list(self.history)[-n:]:
            who = "我" if h.is_self else h.sender
            lines.append(f"{who}: {h.text[:120]}")
        return "\n".join(lines)

    # ---- 判官
    def _judge(self, m: Msg) -> tuple[bool, float, str]:
        prompt = JUDGE_PROMPT.format(context=self._context(self.b["context_size"]),
                                     sender=m.sender, text=m.text[:200])
        out = self.llm.chat(
            [{"role": "user", "content": prompt}],
            model=self.cfg["llm"]["judge_model"], temperature=0.2, max_tokens=60,
        )
        match = re.search(r"\{.*\}", out or "", re.S)
        if not match:
            return False, 0.0, "判官失联"
        try:
            d = json.loads(match.group(0))
        except json.JSONDecodeError:
            return False, 0.0, "判官说胡话"
        return bool(d.get("speak")), float(d.get("confidence") or 0), str(d.get("why") or "")

    # ---- 生成
    def _generate(self, m: Msg) -> str:
        system = (
            self.persona
            + "\n\n你现在要在微信群聊里插一句嘴。要求："
            + f"\n1. 只输出你要说的那句话，不要任何解释、不要引号、不要 markdown。"
            + f"\n2. 一句话，最多 {self.b['max_reply_chars']} 个字。"
            + "\n3. 顺着大家正在聊的话题，别突然开新话题，别总结，别说教。"
            + "\n4. 对方如果是在问你，就直接回答；如果是在抛梗，就接梗。"
        )
        user = f"最近的群聊：\n{self._context(self.b['context_size'])}\n\n现在 {m.sender} 说：{m.text[:300]}"
        out = self.llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        reply = sanitize(out, self.b["max_reply_chars"])
        if reply and reply == m.text.strip():
            return ""
        return reply

    # ---- 发送
    def _deliver(self, reply: str, now: float, kind: str) -> None:
        if self.s.get("dry_run", True):
            log("DRYRUN", f"本来会发：{reply}")
            # 假跑时把这次也记进历史，方便观察上下文是否合理
            self.history.append(Msg("", "我", reply, True, None))
            self.budget.mark(now, kind)
            return

        parts = split_parts(reply, self.b["reply_parts"])
        ok = False
        for i, p in enumerate(parts):
            if i:
                time.sleep(self.b["part_gap_seconds"])
            if self.backend.send(p):
                ok = True
                log("已发", p)
                self.history.append(Msg("", "我", p, True, None))
            else:
                log("失败", f"这条没发出去：{p}")
                break
        if ok:
            self.budget.mark(now, kind)


# ---------------------------------------------------------------- 入口

def main() -> None:
    ap = argparse.ArgumentParser(description="微信群 AI 插话机器人")
    ap.add_argument("-c", "--config", default=str(HERE / "config.json"))
    ap.add_argument("--dry-run", action="store_true", help="只打印不真的发送")
    ap.add_argument("--offline", action="store_true", help="不调用 LLM，用固定话术（测流程用）")
    ap.add_argument("--mock", default="", help="用剧本文件模拟群消息，不连接微信")
    ap.add_argument("--interval", type=float, default=1.2, help="剧本消息间隔秒数")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    if args.dry_run:
        cfg["safety"]["dry_run"] = True

    llm = LLM(cfg["llm"], offline=args.offline)
    if args.mock:
        backend = MockBackend(Path(args.mock), interval=args.interval)
    else:
        backend = WeChatBackend(cfg)

    log("配置", f"群={cfg['group']}  假跑={cfg['safety']['dry_run']}  "
                f"抽样=1/{cfg['behavior']['sample_every']}  "
                f"冷却={cfg['behavior']['cooldown_seconds']}s")
    GroupBot(cfg, backend, llm).start()


if __name__ == "__main__":
    main()
