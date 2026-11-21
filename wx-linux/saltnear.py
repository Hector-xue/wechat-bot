import sys, time
sys.path.insert(0, "/root/dsh/wx-linux/wd")
from key_scan_common import collect_db_files, verify_enc_key
DBDIR = "/home/wxuser/xwechat_files/wxid_REPLACED/db_storage"
PID = int(sys.argv[1])
db_files, salt_to_dbs = collect_db_files(DBDIR)
pages = {s: p for rel, path, sz, s, p in db_files}
# 按出现次数少、最小的库优先
targets = sorted(pages, key=lambda s: len(salt_to_dbs[s]))[:6]
mem = open(f"/proc/{PID}/mem","rb",0)
regions=[]
for line in open(f"/proc/{PID}/maps"):
    p=line.split()
    if "r" not in p[1]: continue
    a,b=p[0].split("-"); a,b=int(a,16),int(b,16)
    if b-a>1_500_000_000: continue
    regions.append((a,b-a))
found={}; t0=time.time(); nhit=0; ntest=0
for base,size in regions:
    try:
        mem.seek(base); buf=mem.read(size)
    except Exception: continue
    if not buf: continue
    for salt_hex in targets:
        if salt_hex in found: continue
        salt = bytes.fromhex(salt_hex)
        i = buf.find(salt)
        cnt = 0
        while i != -1 and cnt < 6:
            nhit += 1
            lo, hi = max(0, i-8192), min(len(buf), i+8192)
            for off in range(lo, hi-32, 8):
                cand = buf[off:off+32]
                if cand == bytes(32): continue
                ntest += 1
                try:
                    if verify_enc_key(cand, pages[salt_hex]):
                        found[salt_hex]=cand.hex()
                        print(f"FOUND salt={salt_hex} key={cand.hex()} db={salt_to_dbs[salt_hex]}", flush=True)
                        break
                except Exception: pass
            i = buf.find(salt, i+1); cnt += 1
print(f"salt 命中 {nhit} 处, 试了 {ntest} 个候选, 找到 {len(found)} 个密钥, {time.time()-t0:.0f}s")
