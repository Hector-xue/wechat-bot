#!/usr/bin/env python3
"""解析 SQLite b-tree 叶子页，还原记录字段（不需要密钥、不需要完整库）。"""
import sys, os, json

def varint(b, i):
    v = 0
    for k in range(9):
        if i >= len(b): return v, i
        c = b[i]; i += 1
        if k == 8:
            return (v << 8) | c, i
        v = (v << 7) | (c & 0x7F)
        if not (c & 0x80):
            return v, i
    return v, i

def decode_record(payload):
    hlen, i = varint(payload, 0)
    types, j = [], i
    guard = 0
    while j < hlen and j < len(payload) and guard < 200:
        guard += 1
        t, nj = varint(payload, j)
        if nj <= j:
            break
        j = nj
        types.append(t)
    vals, off = [], hlen
    for t in types:
        if t == 0: vals.append(None)
        elif t in (1,2,3,4): 
            n = {1:1,2:2,3:3,4:4}[t]
            vals.append(int.from_bytes(payload[off:off+n], "big", signed=True)); off += n
        elif t == 5:
            vals.append(int.from_bytes(payload[off:off+6], "big", signed=True)); off += 6
        elif t == 6:
            vals.append(int.from_bytes(payload[off:off+8], "big", signed=True)); off += 8
        elif t == 7:
            vals.append(payload[off:off+8]); off += 8
        elif t == 8: vals.append(0)
        elif t == 9: vals.append(1)
        elif t >= 12:
            n = (t - 12) // 2
            raw = payload[off:off+n]; off += n
            vals.append(raw if t % 2 == 0 else raw.decode("utf-8", "replace"))
        else:
            vals.append(None)
    return vals

def parse_leaf(path):
    b = open(path, "rb").read()
    if not b or b[0] != 0x0D:
        return []
    ncell = int.from_bytes(b[3:5], "big")
    rows = []
    for k in range(ncell):
        p = 8 + 2*k
        if p + 2 > len(b): break
        cell = int.from_bytes(b[p:p+2], "big")
        if cell >= len(b): continue
        plen, i = varint(b, cell)
        rowid, i = varint(b, i)
        payload = b[i:i+plen]
        try:
            rows.append((rowid, decode_record(payload)))
        except Exception:
            continue
    return rows

if __name__ == "__main__":
    for f in sys.argv[1:]:
        rows = parse_leaf(f)
        if not rows: continue
        print(f"=== {os.path.basename(f)}: {len(rows)} 行")
        for rowid, vals in rows[:6]:
            txt = [v for v in vals if isinstance(v, str) and len(v) > 2][:4]
            print(f"  rowid={rowid} {txt}")
