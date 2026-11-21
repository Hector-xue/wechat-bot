#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
消息处理 stage 流水线
=====================

借鉴 AstrBot 的 pipeline 设计：消息进来走一串可插拔的 stage。
每个 stage 处理一个 MsgContext，可以设置 ctx.skip 提前终止。

顺序：
    preprocess → rate_limit → safety → wake → judge → agent → respond
"""

import re
import time
from collections import deque


class MsgContext:
    def __init__(self, text, ts, sender=""):
        self.text = text          # 已剥离发送者前缀的正文
        self.ts = ts
        self.sender = sender      # 发送者 wxid（可能为空）
        self.skip = False         # 置 True 则终止后续 stage
        self.skip_reason = ""
        self.reply_lines = []     # 要发的文本（可能多句）
        self.reply_image = ""     # 要发的图片路径
        self.mentioned = False    # 是否被点名
        self.report = False       # 是否触发群报
        self.direct = False       # 已直接备好回复，跳过 AgentStage

    def stop(self, reason):
        self.skip = True
        self.skip_reason = reason


class Stage:
    name = "stage"

    def process(self, bot, ctx):
        return ctx


class PreprocessStage(Stage):
    name = "preprocess"

    def process(self, bot, ctx):
        # 已由 scan() 剥离前缀；这里做去重与记录
        if bot.norm(ctx.text) in bot.sent_norm or (ctx.ts, ctx.text) in bot.seen:
            ctx.stop("重复/自己发过的")
            return ctx
        # 时效过滤：超过 3 分钟的消息不再回应，避免对"回放"的旧消息乱答
        MAX_AGE = 180
        if ctx.ts and time.time() - ctx.ts > MAX_AGE:
            ctx.stop(f"过期消息（{int(time.time()-ctx.ts)}s 前）")
            bot.seen.add((ctx.ts, ctx.text))
            return ctx
        bot.seen.add((ctx.ts, ctx.text))
        bot.recent.append(("群友", ctx.text))
        sname = bot.resolve_name(ctx.sender) or "群友"
        bot.history.append(("user", ctx.text, sname))
        bot.conv.setdefault(sname, deque(maxlen=8)).append(("user", ctx.text))
        lag = time.time() - ctx.ts if ctx.ts else 0
        bot.log(f"收到：{ctx.text[:30]}（延迟 {lag:.1f}s）")
        bot.wxlog.event("recv", chat=bot.chat, text=ctx.text, latency=lag)
        return ctx


class RateLimitStage(Stage):
    name = "rate_limit"

    def process(self, bot, ctx):
        # 不再用全局冷却挡消息——@ 必须回，主动插话由 JudgeStage 自己限频。
        # 这里只防"同一秒连发"这种极端情况。
        return ctx


class SafetyStage(Stage):
    name = "safety"

    def process(self, bot, ctx):
        text = ctx.text or ""
        # 1) 自定义屏蔽词
        for w in bot.cfg.get("blocked_words") or []:
            if w and w in text:
                ctx.stop(f"命中屏蔽词 {w}")
                return ctx
        # 2) 正则规则（抓"台湾回归""香港示威"这类组合，词表抓不到）
        for pat in bot.cfg.get("blocked_patterns") or []:
            try:
                if re.search(pat, text):
                    bot.log(f"敏感组合命中 /{pat[:20]}/，不接")
                    bot.wxlog.event("error", chat=bot.chat, text=text,
                                    detail=f"敏感组合:{pat[:30]}")
                    ctx.stop("敏感话题（组合规则）")
                    return ctx
            except re.error:
                continue
        # 3) 敏感话题硬规则：涉政/涉黄/涉赌/涉毒/暴力，一概不接
        cats = bot.cfg.get("blocked_keywords") or {}
        for cat, words in cats.items():
            for w in words:
                if w and w in text:
                    bot.log(f"敏感话题[${cat}]命中「{w}」，不接")
                    bot.wxlog.event("error", chat=bot.chat, text=text,
                                    detail=f"敏感话题-{cat}:{w}")
                    ctx.stop(f"敏感话题（{cat}）")
                    return ctx
        return ctx


class WakeStage(Stage):
    name = "wake"

    def process(self, bot, ctx):
        # 0) 人设切换指令
        m = re.search(r"(?:切换|换)(?:个|下)?(?:人设|人格|性格|语气)[\s：:]*([\u4e00-\u9fa5A-Za-z]+)", ctx.text)
        if m:
            want = m.group(1).strip()
            personas = bot.cfg.get("personas") or {}
            hit = next((n for n in personas if n in want or want in n), None)
            if hit:
                bot.cfg["persona"] = personas[hit]
                ctx.direct = True
                ctx.reply_lines = [f"好嘞，现在我是「{hit}」"]
                bot.save_state()
            return ctx
        # 1) 触发词（群报）
        if any(k in ctx.text for k in bot.TRIGGERS):
            ctx.report = True
            return ctx
        # 2) 从 @ 里动态学习称呼，但只在"直接喊话"时（@X 在吗 / @X你 / @X？）
        for m in re.finditer(r"@([^\s@，。！？、]{1,20})", ctx.text):
            name = m.group(1).strip()
            tail = ctx.text[m.end():m.end() + 6]
            direct = bool(re.search(r"(在吗|在不在|你|？|\?|呢|帮我|问下)", tail))
            if name and direct and name not in bot.learned_names:
                bot.learned_names.add(name)
                bot.log(f"学到新称呼：{name}")
                bot.save_state()
        names = list(bot.cfg.get("my_names") or []) + sorted(bot.learned_names)
        ctx.mentioned = any(n and n in ctx.text for n in names)
        # 话题接力：刚跟机器人聊过的人，短时间内再接话（即使没@）也视为在跟机器人说
        if not ctx.mentioned and ctx.sender and ctx.sender == bot.last_addressed_wxid \
                and time.time() - bot.last_addressed_ts < float(bot.cfg.get("follow_up_window", 90)):
            ctx.mentioned = True
            bot.log(f"话题接力：{bot.resolve_name(ctx.sender) or ctx.sender} 接着聊")
        if ctx.mentioned:
            return ctx
        # 3) 主动参与开关
        if not bot.cfg.get("auto_join", False):
            if bot.cfg.get("mention_only", False):
                ctx.stop("未点名")
            return ctx
        return ctx


class JudgeStage(Stage):
    name = "judge"

    def process(self, bot, ctx):
        if ctx.mentioned or ctx.report or not bot.cfg.get("auto_join", False):
            return ctx
        bot.msg_since_judge += 1
        every = max(1, int(bot.cfg.get("auto_join_every", 3)))
        if bot.msg_since_judge % every != 0:
            ctx.stop("抽样未命中")
            return ctx
        if time.time() - bot.last_proactive < bot.cfg.get("auto_join_cooldown", 120):
            ctx.stop("主动冷却中")
            return ctx
        speak, score, why = bot.judge(ctx.text)
        if not speak or score < bot.cfg.get("judge_threshold", 0.6):
            ctx.stop(f"判官不接（{why} {score:.2f}）")
            return ctx
        if bot.random.random() > bot.cfg.get("auto_join_probability", 0.4):
            ctx.stop("掷骰子没过")
            return ctx
        bot.log(f"主动接话（{why} {score:.2f}）")
        bot.last_proactive = time.time()
        return ctx


class AgentStage(Stage):
    name = "agent"

    def process(self, bot, ctx):
        if ctx.direct:
            return ctx
        if ctx.report:
            rep = bot.on_demand_report(ctx.text)
            if rep:
                ctx.reply_image, one = rep
                ctx.reply_lines = [one]
        else:
            t0 = time.time()
            # 只有明确需要深度时才用强模型（否则每次 @ 都慢 3-10 秒）
            deep = bool(getattr(ctx, "mentioned", False)) and bool(
                re.search(r"深入|详细|分析|为什么|原理|对比|方案|建议|怎么回事|怎么解决",
                          ctx.text or ""))
            reply = bot.ask(ctx.text, sender=ctx.sender, deep=deep)
            bot.gen_ms = int((time.time() - t0) * 1000)
            if not reply:
                bot.wxlog.event("error", chat=bot.chat, text=ctx.text, detail="LLM 无回复")
                ctx.stop("LLM 无回复")
                return ctx
            if reply.strip().upper().startswith("[SKIP]") or reply.strip().upper() == "SKIP":
                bot.log(f"模型选择不答：{ctx.text[:24]}")
                ctx.stop("模型弃权")
                return ctx
            ctx.reply_lines = bot.split_reply(reply)
            if not ctx.reply_lines:
                bot.wxlog.event("error", chat=bot.chat, text=ctx.text, detail="空回复")
                ctx.stop("空回复")
        return ctx


class RespondStage(Stage):
    name = "respond"

    def process(self, bot, ctx):
        ok_all = True
        if ctx.reply_image:
            ok_all = bot.send_image(ctx.reply_image)
        for i, line in enumerate(ctx.reply_lines):
            if i:
                time.sleep(float(bot.cfg.get("reply_gap_seconds", 1.6)))
            if not bot.send(line):
                ok_all = False
                break
        bot.wxlog.event("reply", chat=bot.chat, text="\n".join(ctx.reply_lines),
                        gen_ms=getattr(bot, "gen_ms", 0),
                        send_ms=getattr(bot, "_last_send_ms", 0),
                        ok=1 if ok_all else 0)
        if ok_all:
            bot.last_reply = time.time()
            joined = "\n".join(ctx.reply_lines)
            bot.history.append(("assistant", joined, ""))
            sname = bot.resolve_name(ctx.sender) or "群友"
            bot.conv.setdefault(sname, deque(maxlen=8)).append(("assistant", joined))
            if ctx.sender:
                bot.last_addressed_wxid = ctx.sender
                bot.last_addressed_ts = time.time()
            bot.compress_history()
            bot.save_state()
        return ctx


PIPELINE = [
    PreprocessStage(),
    RateLimitStage(),
    SafetyStage(),
    WakeStage(),
    JudgeStage(),
    AgentStage(),
    RespondStage(),
]


def run(bot, text, ts, sender=""):
    ctx = MsgContext(text, ts, sender)
    for stage in PIPELINE:
        if ctx.skip:
            if ctx.skip_reason:
                bot.log(f"跳过：{ctx.skip_reason}")
            return ctx
        try:
            stage.process(bot, ctx)
        except Exception as e:
            bot.log(f"[{stage.name}] 异常: {e!r}")
            bot.wxlog.event("error", detail=f"{stage.name}:{e!r}"[:200])
            return ctx
    return ctx
