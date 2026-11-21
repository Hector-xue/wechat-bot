import re, sys, time
from key_scan_common import collect_db_files, verify_enc_key

DBDIR = "/home/wxuser/xwechat_files/wxid_REPLACED/db_storage"
PID = int(sys.argv[1])
db_files, salt_to_dbs = collect_db_files(DBDIR)
page_by_salt = {s: page1 for rel, path, sz, s, page1 in db_files}
re64 = re.compile(rb"(?<![0-9a-fA-F])([0-9a-fA-F]{64})(?![0-9a-fA-F])")
mem = open(f"/proc/{PID}/mem", "rb", 0)
cands = set()
t0 = time.time()
regions = []
for line in open(f"/proc/{PID}/maps"):
    p = line.split()
    if "r" not in p[1]: continue
    a, b = p[0].split("-"); a, b = int(a,16), int(b,16)
    if b-a > 1_500_000_000: continue
    regions.append((a, b-a))
for base, size in regions:
    try:
        mem.seek(base); buf = mem.read(size)
    except Exception: continue
    for m in re64.finditer(buf or b""):
        cands.add(m.group(1).decode())
print(f"收集 {len(cands)} 个 64 位 hex 候选, {time.time()-t0:.0f}s", flush=True)
found = {}
for i, h in enumerate(cands):
    kb = bytes.fromhex(h)
    for s, page1 in page_by_salt.items():
        if s in found: continue
        try:
            if verify_enc_key(kb, page1):
                found[s] = h
                print(f"FOUND salt={s} key={h} db={salt_to_dbs[s]}", flush=True)
        except Exception: pass
    if (i+1) % 500 == 0:
        print(f"  ...{i+1}/{len(cands)} 验证中, 已找到 {len(found)}", flush=True)
print(f"完成: 找到 {len(found)}/{len(page_by_salt)} 个密钥, 用时 {time.time()-t0:.0f}s")
