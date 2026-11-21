import gdb, json, os, re, time
OUT = "/root/dsh/wx-linux/logs/aesenc_hits.jsonl"
BASE = int(os.environ.get("WXBASE", "0"), 16)
OFFS = [int(x.strip(), 16) for x in open("/tmp/aesenc_addrs.txt") if x.strip()]
DEADLINE = time.time() + 120

log = open(OUT, "a", buffering=1)
hits = [0]

def xmm_bytes(i):
    try:
        txt = gdb.execute(f"p $xmm{i}.v16_int8", to_string=True)
        nums = re.findall(r"-?\d+", txt)
        b = [int(x) & 0xFF for x in nums]
        return bytes(b[:16]) if len(b) >= 16 else None
    except Exception:
        return None

class Kp(gdb.Breakpoint):
    def __init__(self, addr):
        super().__init__(f"*{addr}", internal=True)
        self.silent = True
    def stop(self):
        hits[0] += 1
        regs = {}
        for i in range(16):
            v = xmm_bytes(i)
            if v: regs[i] = v.hex()
        log.write(json.dumps({"t": round(time.time(),1), "regs": regs}) + "\n")
        if hits[0] >= 60 or time.time() > DEADLINE:
            gdb.execute("detach"); gdb.execute("quit")
        return False

for off in OFFS:
    Kp(BASE + off)
log.write(json.dumps({"start": len(OFFS)}) + "\n")
gdb.execute("continue")
