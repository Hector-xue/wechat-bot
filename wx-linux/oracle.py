#!/usr/bin/env python3
"""内存候选字节 -> 直接用 sqlcipher 试着开库。能开就是密钥。"""
import shutil, sqlite3, sys, time
import sqlcipher3

PID = sys.argv[1]
DB = "/home/wxuser/xwechat_files/wxid_REPLACED/db_storage/contact/contact.db"
PROBE = "/tmp/probe.db"
NEEDLES = [b"db_storage", b"contact.db", b"message_0.db", b"key_info"]

shutil.copyfile(DB, PROBE)
regions = []
for line in open(f"/proc/{PID}/maps"):
    p = line.split()
    if "r" not in p[1]:
        continue
    a, b = p[0].split("-")
    if b"memfd" in line.encode() or "/dev/" in line:
        continue
    regions.append((int(a, 16), int(b, 16)))

mem = open(f"/proc/{PID}/mem", "rb", 0)


def read(addr, size):
    try:
        mem.seek(addr)
        return mem.read(size)
    except Exception:
        return b""


def try_key(k):
    try:
        con = sqlcipher3.connect(PROBE)
        con.execute(f"PRAGMA key = \"x'{k.hex()}'\"")
        ok = con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        con.close()
        return ok is not None
    except Exception:
        return False


tested = 0
t0 = time.time()
for base, end in regions:
    size = min(end - base, 64 * 1024 * 1024)
    buf = read(base, size)
    if not buf:
        continue
    for needle in NEEDLES:
        i = buf.find(needle)
        n = 0
        while i != -1 and n < 3:
            lo, hi = max(0, i - 16384), min(len(buf), i + 16384)
            for off in range(lo, hi - 32, 8):
                cand = buf[off:off + 32]
                if cand == bytes(32):
                    continue
                tested += 1
                if try_key(cand):
                    print(f"FOUND key={cand.hex()} 地址=0x{base+off:x} 试了 {tested} 次 {time.time()-t0:.0f}s")
                    sys.exit(0)
            i = buf.find(needle, i + 1)
            n += 1
print(f"没找到。试了 {tested} 个候选，{time.time()-t0:.0f}s")
