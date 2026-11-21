#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""联网取实时信息：今日新闻(60s) / 知乎热搜，给机器人注入当前数据"""
import json
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def daily_news():
    """60s 每日新闻：返回 [(日期, [新闻...])]"""
    try:
        d = json.loads(_get("https://60s.viki.moe/v2/60s"))
        data = d.get("data") or {}
        return data.get("date", ""), data.get("news", [])
    except Exception:
        return "", []


def hot_topics():
    """知乎热榜：返回 [标题...]"""
    try:
        d = json.loads(_get("https://api.zhihu.com/topstory/hot-list?limit=8"))
        return [it.get("target", {}).get("title", "") for it in d.get("data", [])]
    except Exception:
        return []


def _blocked():
    """从 wbot.json 读取敏感词，用于过滤新闻条目"""
    try:
        import json as _j
        d = _j.loads(open("/root/dsh/wx-linux/wbot.json").read())
        out = []
        for words in (d.get("blocked_keywords") or {}).values():
            out.extend(words)
        return out
    except Exception:
        return []


def _sensitive(item, words):
    return any(w and w in item for w in words)


def fetch_for(text):
    """根据消息内容判断要不要联网取数据，返回注入文本（空串=不需要）"""
    t = text or ""
    if any(k in t for k in ("新闻", "热搜", "热点", "头条", "时事", "最新", "今天发生", "最近发生")):
        date, items = daily_news()
        bw = _blocked()
        items = [x for x in items if not _sensitive(x, bw)]   # 过滤涉政等敏感条目
        lines = []
        if date:
            lines.append(f"今天是 {date}，主要新闻：")
        for i, it in enumerate(items[:8], 1):
            lines.append(f"{i}. {it}")
        if lines:
            return "\n".join(lines)
    if any(k in t for k in ("热搜", "热点", "头条")):
        items = [x for x in hot_topics() if not _sensitive(x, _blocked())]
        if items:
            return "当前知乎热搜：\n" + "\n".join(f"- {x}" for x in items[:8])
    return ""


if __name__ == "__main__":
    print("=== 今日新闻 ===")
    d, items = daily_news()
    print(d, "共", len(items), "条")
    for it in items[:3]:
        print("  ", it)
    print("=== 热搜 ===")
    for x in hot_topics()[:3]:
        print("  ", x)
