#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 contact.db 捕获页里建 wxid -> 昵称 映射（供引用回复/用户画像用）"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pageparse import parse_leaf  # noqa: E402

META = "/root/dsh/wx-linux/logs/pages_meta.jsonl"
CACHE = "/root/dsh/wx-linux/logs/names.json"


def build_map(meta_path=META, account_hint=None):
    """扫描 contact.db 叶子页，返回 {username: nickname}"""
    m = {}
    if not os.path.exists(meta_path):
        return m
    for line in open(meta_path):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if "file" not in r or "db" not in r:
            continue
        if not r["db"].endswith("contact.db"):
            continue
        if account_hint and account_hint not in r["db"]:
            continue
        f = f"/root/dsh/wx-linux/logs/pages/{r['file']}"
        if not os.path.exists(f):
            continue
        try:
            recs = parse_leaf(f)
        except Exception:
            continue
        for _, vals in recs:
            if len(vals) < 12:
                continue
            u, n = vals[1], vals[11]
            if isinstance(u, str) and isinstance(n, str) and u and n:
                if n.startswith(("http", "CREATE", "v3_", "<")):
                    continue
                if n in ("", "None"):
                    continue
                m[u] = n
    return m


def load(cache=CACHE):
    m = build_map()
    if m:
        try:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            json.dump(m, open(cache, "w"), ensure_ascii=False)
        except OSError:
            pass
    elif os.path.exists(cache):
        try:
            m = json.load(open(cache))
        except Exception:
            m = {}
    return m


def resolve(uid, m):
    if not uid:
        return uid
    return m.get(uid, uid)


if __name__ == "__main__":
    m = load()
    print(f"名字映射 {len(m)} 条")
    for u, n in list(m.items())[:15]:
        print(f"  {u:28s} -> {n}")
