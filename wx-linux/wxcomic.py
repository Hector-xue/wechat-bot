#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""群聊卡通版报告：把金句渲染成漫画对话气泡 + 活跃成员卡牌"""
import hashlib
import os
import re
import sqlite3

from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys_path = os.path.dirname(os.path.abspath(__file__))
FONT = "/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc"
DB = "/root/dsh/wx-linux/messages.db"
OUTDIR = "/root/dsh/wx-linux/reports/png"

PALETTE = [
    (239, 83, 80), (66, 165, 245), (102, 187, 106), (255, 183, 77),
    (171, 71, 188), (38, 198, 218), (255, 138, 101), (121, 134, 203),
]
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
            lines.append(cur); cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def color_for(name):
    h = hashlib.md5(name.encode()).digest()[0]
    return PALETTE[h % len(PALETTE)]


def norm(t):
    return re.sub(r"[\s\W_]+", "", t or "")


def parse_md(md_path):
    quotes, active = [], []
    cur = None
    for ln in open(md_path, encoding="utf-8"):
        s = ln.strip()
        if "金句" in s:
            cur = "quote"; continue
        if "活跃" in s:
            cur = "active"; continue
        if s.startswith("#") and "金句" not in s and "活跃" not in s:
            if s.startswith("##") or s.startswith("**"):
                cur = None
        if cur == "quote" and s.startswith("- "):
            q = s[2:].strip().strip("\"'“”")
            if q:
                quotes.append(strip_emoji(q))
        elif cur == "active" and s.startswith("- "):
            m = re.match(r"- (.+?)：(\d+) 条", s)
            if m:
                active.append((strip_emoji(m.group(1)), int(m.group(2))))
    return quotes, active


def match_sender(quote, con):
    """在消息库里找金句对应的发送者"""
    q = norm(quote)
    if len(q) < 2:
        return ""
    for (text,) in con.execute("select text from msg"):
        m = re.match(r"^([A-Za-z0-9_\-\.]{4,64}):\s*\n(.+)$", (text or ""), re.S)
        if m:
            sender, content = m.group(1), norm(m.group(2))
            if content == q or (len(q) >= 6 and q in content):
                return sender
    return ""


def render(md_path, out_path=None):
    quotes, active = parse_md(md_path)
    con = sqlite3.connect(DB)
    import wxnames
    names = wxnames.load()

    W = 900
    PAD = 40
    BG = (255, 250, 240)          # 暖白
    INK = (33, 33, 33)

    f_title = font(34, "Bold")
    f_sub = font(14)
    f_name = font(15, "Bold")
    f_body = font(19)
    f_big = font(26, "Bold")
    f_small = font(12)

    probe = Image.new("RGB", (W, 10))
    pd = ImageDraw.Draw(probe)
    inner = W - PAD * 2

    # 估高度
    h = PAD + 70 + 30
    panels = []
    for q in quotes:
        sender = match_sender(q, con)
        sname = names.get(sender, "") or (sender or "群友")
        bubble_w = inner - 110
        n_lines = sum(len(wrap(pd, q, f_body, bubble_w - 40)) for _ in [0])
        ph = max(70, n_lines * 30 + 36)
        panels.append((q, sname, ph))
        h += ph + 18
    # 活跃区
    act_h = 0
    if active:
        act_h = 120
        h += act_h + 20
    h += 60
    H = max(h, 360)

    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)

    # 标题
    y = PAD
    dr.ellipse([W - 130, 10, W - 30, 110], fill=(255, 224, 130))
    dr.text((PAD, y), "群聊小剧场", font=f_title, fill=INK)
    y += 44
    stamp = os.path.basename(md_path)[:8]
    dr.text((PAD, y), f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} · 群聊金句精选",
            font=f_sub, fill=(150, 150, 150))
    y += 40

    for q, sname, ph in panels:
        # 头像圆
        c = color_for(sname)
        ax, ay = PAD, y + 4
        dr.ellipse([ax, ay, ax + 56, ay + 56], fill=c)
        first = (sname or "群")[0]
        fw = dr.textlength(first, font=f_big)
        dr.text((ax + 28 - fw / 2, ay + 6), first, font=f_big, fill=(255, 255, 255))
        # 气泡
        bx0, by0 = PAD + 70, y
        bx1, by1 = W - PAD, y + ph
        dr.rounded_rectangle([bx0, by0, bx1, by1], radius=20, fill=(255, 255, 255),
                             outline=(220, 214, 200), width=2)
        # 气泡尾巴（三角）
        dr.polygon([(bx0 + 6, by0 + 26), (bx0 - 14, by0 + 34), (bx0 + 6, by0 + 42)],
                   fill=(255, 255, 255), outline=(220, 214, 200))
        dr.text((bx0 + 22, by0 + 10), sname, font=f_name, fill=c)
        ty = by0 + 36
        for line in wrap(pd, q, f_body, bx1 - bx0 - 40):
            dr.text((bx0 + 22, ty), line, font=f_body, fill=INK)
            ty += 30
        y += ph + 18

    # 活跃卡牌
    if active:
        dr.text((PAD, y + 6), "本场活跃", font=f_name, fill=(120, 120, 120))
        y += 34
        x = PAD
        for name, cnt in active[:6]:
            cw = max(70, dr.textlength(name, font=f_small) + 30)
            cc = color_for(name)
            dr.rounded_rectangle([x, y, x + cw, y + 84], radius=16,
                                 fill=(255, 255, 255), outline=(225, 218, 205), width=2)
            dr.ellipse([x + cw / 2 - 18, y + 10, x + cw / 2 + 18, y + 46], fill=cc)
            fw = dr.textlength((name or "群")[0], font=f_name)
            dr.text((x + cw / 2 - fw / 2, y + 14), (name or "群")[0], font=f_name,
                    fill=(255, 255, 255))
            nw = dr.textlength(name, font=f_small)
            dr.text((x + cw / 2 - nw / 2, y + 52), name, font=f_small, fill=INK)
            cw2 = dr.textlength(f"{cnt}条", font=f_small)
            dr.text((x + cw / 2 - cw2 / 2, y + 68), f"{cnt}条", font=f_small, fill=(150, 150, 150))
            x += cw + 12
        y += 100

    dr.text((W / 2 - 90, H - 40), "群聊小剧场 · 自动生成", font=f_small, fill=(190, 185, 175))

    out = out_path or os.path.join(OUTDIR, os.path.basename(md_path).replace(".md", "-comic.png"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, "PNG")
    return out


if __name__ == "__main__":
    import glob
    md = sorted(glob.glob("/root/dsh/wx-linux/reports/*.md"))[-1]
    print(render(md))
