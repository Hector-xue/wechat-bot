import gdb
import json
import os
import time

OUT = "/root/dsh/wx-linux/logs/key_candidates.jsonl"
BASE = int(os.environ.get("WXBASE", "0"), 16)
ADDR = BASE + 0x923B2E3          # movups (%rdi),%xmm0 —— 用户密钥刚被载入前一刻
MAX_HITS = 5000
DEADLINE = time.time() + 150

log = open(OUT, "a", buffering=1)
hits = [0]


class Kp(gdb.Breakpoint):
    def __init__(self, addr):
        super().__init__(f"*{addr} if $esi == 0x100", internal=True)
        self.silent = True

    def stop(self):
        hits[0] += 1
        try:
            bits = int(gdb.parse_and_eval("$esi"))
            ptr = int(gdb.parse_and_eval("$rdi"))
            if bits in (0x80, 0xC0, 0x100) and ptr:
                n = bits // 8
                data = gdb.selected_inferior().read_memory(ptr, n).tobytes()
                log.write(json.dumps({"t": round(time.time(),1), "bits": bits, "key": data.hex()}) + "\n")
        except Exception as e:
            log.write(json.dumps({"error": str(e)}) + "\n")

        if hits[0] >= MAX_HITS or time.time() > DEADLINE:
            log.write(json.dumps({"done": hits[0]}) + "\n")
            gdb.execute("detach")
            gdb.execute("quit")
        return False


Kp(ADDR)
log.write(json.dumps({"start": ADDR, "hits_target": MAX_HITS}) + "\n")
gdb.execute("continue")
