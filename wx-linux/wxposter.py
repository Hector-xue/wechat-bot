#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""群聊分析海报（浅色版）"""
import os
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT = "/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc"
W = 900
PAD = 46
BG = (247, 248, 250)
WHITE = (255, 255, 255)
INK = (28, 32, 38)
INK2 = (92, 101, 115)
MUTED = (150, 158, 170)
LINE = (232, 236, 241)
BLUE = (47, 128, 237)
AMBER = (222, 150, 42)
GREEN = (16, 168, 125)
EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF]+")


def strip_emoji(t):
    return EMOJI.sub("", t).strip()


def font(size, weight="Regular"):
    try:
        f = ImageFont.truetype(FONT, size, index=0)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        return f
    except Exception:
        return ImageFont.load_default()


def wrap(dr, text, f, max_w):
    lines, cur = [], ""
    for ch in text:
        if dr.textlength(cur + ch, font=f) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def parse(md_path):
    title, span, raw_n, dedup_n, secs, cur = "群聊分析", "", 0, 0, [], None
    for ln in open(md_path, encoding="utf-8"):
        raw = ln.strip()
        if not raw:
            continue
        n = raw.replace("**", "").strip()
        if raw.startswith("# "):
            title = raw[2:].strip(); continue
        if raw.startswith("- 时间范围"):
            span = raw.split("：", 1)[-1].strip(); continue
        if raw.startswith("- 原始"):
            m = re.search(r"原始\s*(\d+)\s*条[，,]\s*去重后\s*(\d+)", raw)
            if m:
                raw_n, dedup_n = int(m.group(1)), int(m.group(2))
            continue
        head = re.sub(r"^#+\s*", "", n)
        if re.match(r"^\d+[.、]\s*\S", head):
            cur = {"head": re.sub(r"^\d+[.、]\s*", "", head), "items": [], "paras": []}
            secs.append(cur); continue
        if cur is None:
            continue
        if raw.startswith("- "):
            cur["items"].append(strip_emoji(raw[2:].strip()))
        else:
            cur["paras"].append(strip_emoji(raw))
    return title, span, raw_n, dedup_n, secs


def shadow_card(img, box, radius=22, blur=10, alpha=26, dy=3):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0, y0 + dy, x1, y1 + dy], radius=radius, fill=(20, 30, 50, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.alpha_composite(layer)


def render(md_path, out_path=None):
    title, span, raw_n, dedup_n, secs = parse(md_path)
    f_badge = font(13)
    f_title = font(36, "Bold")
    f_meta = font(15)
    f_head = font(18, "Medium")
    f_body = font(18)
    f_num = font(24, "Bold")
    f_lab = font(12)
    f_foot = font(12)

    probe = Image.new("RGB", (W, 10))
    pd = ImageDraw.Draw(probe)
    inner = W - PAD * 2 - 48

    # 预估高度
    h = PAD + 40 + 20
    h += len(wrap(pd, title, f_title, inner)) * 50
    h += 30 + 60 + 24                      # meta + chips
    blocks = []
    for sec in secs:
        bh = 30
        items = sec["items"] or sec["paras"]
        for it in items:
            bh += len(wrap(pd, it, f_body, inner - 40)) * 32 + 10
        blocks.append((sec, bh + 46))
        h += bh + 46 + 20
    h += 86
    H = max(h, 420)

    img = Image.new("RGBA", (W, H), BG + (255,))
    dr = ImageDraw.Draw(img)

    # 顶部柔光
    glow = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-W * 0.3, -220, W * 1.3, 190], fill=(120, 170, 255, 26))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))

    y = PAD
    # ---- 封面卡 ----
    cover_h = (30 + 28 + 20 + len(wrap(pd, title, f_title, inner)) * 50
               + (28 if span else 0) + 14 + 62 + 28)
    shadow_card(img, [PAD, y, W - PAD, y + cover_h])
    dr.rounded_rectangle([PAD, y, W - PAD, y + cover_h], radius=22, fill=WHITE,
                         outline=LINE, width=1)
    iy = y + 30
    bw = dr.textlength("群聊分析", font=f_badge) + 30
    dr.rounded_rectangle([PAD + 32, iy, PAD + 32 + bw, iy + 28], radius=14,
                         fill=(235, 243, 255))
    dr.text((PAD + 47, iy + 7), "群聊分析", font=f_badge, fill=BLUE)
    iy += 28 + 20
    for line in wrap(pd, title, f_title, inner):
        dr.text((PAD + 32, iy), line, font=f_title, fill=INK); iy += 50
    if span:
        dr.text((PAD + 32, iy + 4), span, font=f_meta, fill=MUTED); iy += 28
    iy += 14
    # 统计条
    stats = [(str(raw_n), "原始消息"), (str(dedup_n), "去重后"),
             (f"{dedup_n*100//max(raw_n,1)}%", "有效占比")] if raw_n else []
    sx = PAD + 32
    for val, lab in stats:
        cw = max(dr.textlength(val, font=f_num), dr.textlength(lab, font=f_lab)) + 46
        dr.rounded_rectangle([sx, iy, sx + cw, iy + 62], radius=14,
                             fill=(248, 250, 253), outline=LINE)
        dr.text((sx + 23, iy + 9), val, font=f_num, fill=INK)
        dr.text((sx + 23, iy + 40), lab, font=f_lab, fill=MUTED)
        sx += cw + 12
    y += cover_h + 20

    # ---- 内容卡 ----
    for sec, bh in blocks:
        gold = "金句" in sec["head"]
        hero = "概括" in sec["head"]
        accent = GREEN if hero else (AMBER if gold else BLUE)
        fill = (241, 251, 247) if hero else WHITE
        outline = (198, 235, 222) if hero else LINE
        shadow_card(img, [PAD, y, W - PAD, y + bh], alpha=20)
        dr.rounded_rectangle([PAD, y, W - PAD, y + bh], radius=22, fill=fill,
                             outline=outline, width=1)
        dr.rounded_rectangle([PAD + 30, y + 26, PAD + 36, y + 52], radius=3, fill=accent)
        dr.text((PAD + 48, y + 26), sec["head"], font=f_head, fill=accent)
        iy = y + 66
        items = sec["items"] or sec["paras"]
        for it in items:
            if sec["items"]:
                dr.ellipse([PAD + 34, iy + 13, PAD + 41, iy + 20], fill=accent)
                tx, maxw = PAD + 54, inner - 22
            else:
                tx, maxw = PAD + 48, inner - 16
            for line in wrap(pd, it, f_body, maxw):
                dr.text((tx, iy), line, font=f_body, fill=INK if not gold else (90, 62, 16))
                iy += 32
            iy += 10
        y += bh + 20

    foot = "wxpipe 自动生成"
    fw = dr.textlength(foot, font=f_foot)
    dr.text(((W - fw) / 2, H - 40), foot, font=f_foot, fill=(178, 184, 194))

    out = out_path or md_path.replace(".md", ".png").replace("/reports/", "/reports/png/")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.convert("RGB").save(out, "PNG")
    return out


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        print(render(f))
