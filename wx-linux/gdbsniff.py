import gdb
import re
import time

OUT = "/root/dsh/wx-linux/logs/aes_hits.log"
BASE = 0x5615D0641000
OFFS = [0x923A32E + 0xB * i for i in range(6)]   # 密钥扩展的 6 条 aeskeygenassist
MAX_HITS = 400
DEADLINE = time.time() + 120

log = open(OUT, "a", buffering=1)
hits = [0]


def xmm_bytes(name):
    try:
        txt = gdb.execute(f"p $xmm{name}.v16_int8", to_string=True)
        nums = re.findall(r"-?\d+", txt)
        b = [int(x) & 0xFF for x in nums][:16]
        return bytes(b) if len(b) == 16 else None
    except Exception:
        return None


class Kp(gdb.Breakpoint):
    def __init__(self, addr):
        super().__init__(f"*{addr}", internal=False)
        self.silent = True

    def stop(self):
        hits[0] += 1
        t = time.time()
        regs = {}
        for i in range(8):
            v = xmm_bytes(i)
            if v:
                regs[f"xmm{i}"] = v.hex()
        try:
            gprs = {r: int(gdb.parse_and_eval(f"${r}")) for r in ("rsi", "rdx", "rdi", "rcx")}
        except Exception:
            gprs = {}
        log.write(f"HIT {hits[0]} pc={int(gdb.parse_and_eval('$pc')):#x} "
                  f"gprs={gprs} regs={regs}\n")
        if hits[0] >= MAX_HITS or t > DEADLINE:
            log.write("DETACH\n")
            gdb.execute("detach")
            gdb.execute("quit")
        return False


for off in OFFS:
    Kp(BASE + off)

log.write(f"=== 开始 attach, 断点 {len(OFFS)} 个 ===\n")
gdb.execute("continue")
