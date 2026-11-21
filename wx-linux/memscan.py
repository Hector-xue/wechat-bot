#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在微信进程内存里找 SQLCipher 密钥。

判据：用候选 key 解开数据库第一页的第一个块，明文应等于 "SQLite format 3\\0"。
SQLCipher 第一页：前 16 字节是 salt，也是第一块的 IV；密文从 offset 16 开始。
"""
import sys, time
from Crypto.Cipher import AES

PID = sys.argv[1]
DB = sys.argv[2]
NEEDLE = sys.argv[3].encode() if len(sys.argv) > 3 else b"wxid_"
WINDOW = 256 * 1024

db = open(DB, "rb").read(4096)
salt, c1 = db[:16], db[16:32]
target = b"SQLite format 3\x00"
want = bytes(a ^ b for a, b in zip(target, salt))   # D_k(c1) 应该等于这个


def regions():
    out = []
    for line in open(f"/proc/{PID}/maps"):
        p = line.split()
        if "r" not in p[1]:
            continue
        a, b = p[0].split("-")
        out.append((int(a, 16), int(b, 16)))
    return out


def read(addr, size):
    try:
        with open(f"/proc/{PID}/mem", "rb", 0) as f:
            f.seek(addr)
            return f.read(size)
    except (OSError, ValueError):
        return b""


def test(buf, start, hits, stats):
    n = len(buf)
    for off in range(0, n - 32, 8):
        key = buf[off:off + 32]
        stats[0] += 1
        try:
            if AES.new(key, AES.MODE_ECB).decrypt(c1) == want:
                hits.append((start + off, key.hex()))
                return True
        except Exception:
            pass
    return False


stats = [0]
t0 = time.time()
total = 0
for base, end in regions():
    size = min(end - base, 512 * 1024 * 1024)
    buf = read(base, size)
    total += len(buf)
    if NEEDLE not in buf:
        continue
    idx = buf.find(NEEDLE)
    while idx != -1:
        lo = max(0, idx - WINDOW)
        hi = min(len(buf), idx + WINDOW)
        hits = []
        if test(buf[lo:hi], base + lo, hits, stats):
            print("找到密钥:", hits[0][1], "偏移", hex(hits[0][0]))
            print(f"尝试 {stats[0]} 个候选，用时 {time.time()-t0:.1f}s")
            sys.exit(0)
        idx = buf.find(NEEDLE, idx + 1)
print(f"没找到。扫描 {total/1e6:.0f}MB，试了 {stats[0]} 个候选，用时 {time.time()-t0:.1f}s")
