#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""群聊分析报告渲染器：markdown -> 精美自包含 HTML（零依赖）"""
import html
import os
import re

TEMPLATE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#f7f8fa;color:#1c2026;
 font:16px/1.85 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
 padding:28px 16px 60px;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:680px;margin:0 auto}}
.cover{{background:#fff;border:1px solid #e8ecf1;border-radius:22px;padding:30px 30px 26px;
 box-shadow:0 6px 24px rgba(20,30,50,.06);margin-bottom:18px;
 background-image:radial-gradient(120% 90% at 12% 0%,#eef4ff 0%,#fff 55%)}}
.badge{{display:inline-block;font-size:12px;letter-spacing:1px;color:#2f80ed;
 background:#ebf3ff;padding:5px 14px;border-radius:999px;margin-bottom:18px}}
h1{{font-size:30px;line-height:1.35;font-weight:700;letter-spacing:.3px}}
.sub{{color:#9aa1ab;font-size:14px;margin-top:8px}}
.chips{{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}}
.chip{{background:#f8fafd;border:1px solid #e8ecf1;border-radius:14px;padding:10px 20px;min-width:92px}}
.chip b{{display:block;font-size:23px;font-weight:700;color:#1c2026;line-height:1.3}}
.chip span{{font-size:12px;color:#9aa1ab}}
.card{{background:#fff;border:1px solid #e8ecf1;border-radius:22px;padding:24px 28px;
 margin-bottom:16px;box-shadow:0 6px 24px rgba(20,30,50,.05)}}
.card h2{{font-size:17px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:10px}}
.card h2::before{{content:"";width:4px;height:20px;border-radius:3px;background:#2f80ed}}
.card li{{list-style:none;position:relative;padding-left:22px;margin:11px 0;color:#2b3038}}
.card li::before{{content:"";position:absolute;left:2px;top:12px;width:7px;height:7px;
 border-radius:50%;background:#2f80ed}}
.gold h2{{color:#c98518}}.gold h2::before{{background:#de962a}}
.gold li::before{{background:#de962a}}.gold li{{color:#6b4a12}}
.hero{{background:#f1fbf7;border-color:#c6ebde}}
.hero h2{{color:#10a87d}}.hero h2::before{{background:#10a87d}}
.hero p{{font-size:17px;color:#1c2026}}
.foot{{text-align:center;color:#b2b8c2;font-size:12px;margin-top:26px}}
@media(max-width:520px){{h1{{font-size:23px}}.cover,.card{{padding:20px}}}}
</style></head><body><div class="wrap">
<div class="cover">
<div class="badge">群聊分析</div>
<h1>{title}</h1>
<div class="sub">{meta}</div>
<div class="chips">{chips}</div>
</div>
{body}
<div class="foot">{stamp} · wxpipe 自动生成</div>
</div></body></html>"""

ICONS = {"话题": "💬", "金句": "✨", "概括": "🎯", "亮点": "✨", "建议": "💡"}


def _inline(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t


def parse(md_path):
    md = open(md_path, encoding="utf-8").read()
    title, meta, sections, cur = "群聊分析", "", [], None
    raw_n = dedup_n = 0
    span = ""

    for ln in md.splitlines():
        raw = ln.strip()
        if not raw:
            continue
        s_norm = raw.replace("**", "").strip()
        if raw.startswith("# "):
            title = raw[2:].strip()
            continue
        if raw.startswith("- 时间范围"):
            span = raw.split("：", 1)[-1].strip()
            continue
        if raw.startswith("- 原始"):
            m = re.search(r"原始\s*(\d+)\s*条[，,]\s*去重后\s*(\d+)", raw)
            if m:
                raw_n, dedup_n = int(m.group(1)), int(m.group(2))
            continue
        # 两种标题形式： "## 1. 主要话题" 或 "**1. 主要话题**"
        head = re.sub(r"^#+\s*", "", s_norm)
        if re.match(r"^\d+[.、]\s*\S", head):
            cur = {"head": head, "items": [], "paras": []}
            sections.append(cur)
            continue
        if cur is None:
            continue
        if raw.startswith("- "):
            cur["items"].append(raw[2:].strip())
        else:
            cur["paras"].append(raw)
    return title, span, raw_n, dedup_n, sections


def render(md_path, out_dir=None):
    title, span, raw_n, dedup_n, sections = parse(md_path)
    chips = ""
    if span:
        chips += f'<div class="chip"><b>{_inline(span)}</b><span>时间范围</span></div>'
    if raw_n:
        chips += f'<div class="chip"><b>{raw_n}</b><span>原始消息</span></div>'
    if dedup_n:
        chips += f'<div class="chip"><b>{dedup_n}</b><span>去重后</span></div>'
    if raw_n and dedup_n:
        chips += f'<div class="chip"><b>{dedup_n * 100 // max(raw_n, 1)}%</b><span>有效占比</span></div>'

    body = ""
    for sec in sections:
        head, items, paras = sec["head"], sec["items"], sec["paras"]
        key = next((k for k in ICONS if k in head), "")
        icon = ICONS.get(key, "")
        name = re.sub(r"^\d+[.、]\s*", "", head)
        cls = "card hero-card" if "概括" in head else \
              ("card gold" if "金句" in head else "card")
        inner = f'<h2>{icon} {_inline(name)}</h2>'
        if items:
            inner += "<ul>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + "</ul>"
        if paras:
            inner += "".join(f"<p>{_inline(x)}</p>" for x in paras)
        body += f'<div class="{cls}">{inner}</div>'

    stamp = os.path.basename(md_path)[:8]
    out = TEMPLATE.format(title=_inline(title),
                          meta=f"{span}" if span else "",
                          chips=chips, body=body or "<div class='card'>（无内容）</div>",
                          stamp=f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}")
    out_dir = out_dir or os.path.join(os.path.dirname(md_path), "html")
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, os.path.basename(md_path).replace(".md", ".html"))
    open(dst, "w", encoding="utf-8").write(out)
    return dst


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        print(render(f))
