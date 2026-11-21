import re, sys, time
from key_scan_common import collect_db_files, verify_enc_key

DBDIR = "/home/wxuser/xwechat_files/wxid_REPLACED/db_storage"
PID = int(sys.argv[1])
db_files, salt_to_dbs = collect_db_files(DBDIR)
remaining = set(salt_to_dbs)
hex_re = re.compile(rb"x'([0-9a-fA-F]{96})'")
bare_re = re.compile(rb"(?<![0-9a-fA-F])([0-9a-fA-F]{96})(?![0-9a-fA-F])")

mem = open(f"/proc/{PID}/mem", "rb", 0)
total = 0; npat = 0; found = {}
t0 = time.time()
regions = []
for line in open(f"/proc/{PID}/maps"):
    p = line.split()
    if "r" not in p[1]:
        continue
    a, b = p[0].split("-")
    a, b = int(a, 16), int(b, 16)
    if b - a > 1_500_000_000:
        continue
    regions.append((a, b - a))

for base, size in regions:
    try:
        mem.seek(base); buf = mem.read(size)
    except Exception:
        continue
    if not buf:
        continue
    total += len(buf)
    for rx, kind in ((hex_re, "quoted"), (bare_re, "bare")):
        for m in rx.finditer(buf):
            npat += 1
            h = m.group(1).decode()
            key, salt = h[:64], h[64:]
            if salt not in remaining:
                continue
            kb = bytes.fromhex(key)
            for rel, path, sz, s, page1 in db_files:
                if s == salt and verify_enc_key(kb, page1):
                    found[salt] = key
                    remaining.discard(salt)
                    print(f"FOUND({kind}) salt={salt} key={key} db={rel}", flush=True)
                    break
    if not remaining:
        break
print(f"扫描 {total/1e6:.0f}MB, 命中 hex 模式 {npat} 个, 找到密钥 {len(found)}/{len(salt_to_dbs)}, {time.time()-t0:.0f}s")
