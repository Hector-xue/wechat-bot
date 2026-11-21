import gdb
import json
import os

OUT = "/root/dsh/wx-linux/logs/pages"
os.makedirs(OUT, exist_ok=True)
LOG = open("/root/dsh/wx-linux/logs/page_capture2.log", "a", buffering=1)
PID = gdb.selected_inferior().pid

state = {"pending": None, "n": 0}
inf = gdb.selected_inferior()


def fd_is_db(fd):
    try:
        p = os.readlink(f"/proc/{PID}/fd/{fd}")
        return "db_storage" in p
    except Exception:
        return False


def dump_pending():
    p = state["pending"]
    if not p:
        return
    buf, cnt = p
    state["pending"] = None
    try:
        data = inf.read_memory(buf, min(cnt, 4096)).tobytes()
        state["n"] += 1
        open(f"{OUT}/q{state['n']:05d}.bin", "wb").write(data)
        LOG.write(json.dumps({"n": state["n"], "buf": hex(buf),
                              "head": data[:16].hex()}) + "\n")
    except Exception as e:
        LOG.write(json.dumps({"err": str(e)}) + "\n")


class Watch(gdb.Breakpoint):
    """缓冲区被写入 —— 说明解密落在这一页上。"""
    def __init__(self, addr, buf, cnt):
        super().__init__(f"*(long*)0x{addr:x}", internal=True, temporary=True)
        self.silent = True
        self.buf = buf
        self.cnt = cnt

    def stop(self):
        state["pending"] = (self.buf, self.cnt)
        return False


class Pread(gdb.Breakpoint):
    def __init__(self):
        super().__init__("pread64", internal=True)
        self.silent = True

    def stop(self):
        try:
            fd = int(gdb.parse_and_eval("$rdi"))
            buf = int(gdb.parse_and_eval("$rsi"))
            cnt = int(gdb.parse_and_eval("$rdx"))
        except Exception:
            return False
        if cnt < 1024 or not fd_is_db(fd):
            return False
        dump_pending()          # 上一页此时已解密完成
        state["pending"] = (buf, cnt)
        return False


Pread()
LOG.write(json.dumps({"started": True}) + "\n")
try:
    gdb.execute("continue")
finally:
    dump_pending()
