import gdb
import json
import os

OUT = "/root/dsh/wx-linux/logs/pages"
META = "/root/dsh/wx-linux/logs/pages_meta.jsonl"
os.makedirs(OUT, exist_ok=True)
gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set breakpoint pending on")
log = open(META, "a", buffering=1)
inf = gdb.selected_inferior()
state = {"pending": None, "n": 0}


def fd_path(fd):
    try:
        pid = gdb.selected_inferior().pid
        return os.readlink(f"/proc/{pid}/fd/{fd}")
    except Exception:
        return ""


class Pread(gdb.Breakpoint):
    def __init__(self):
        super().__init__("pread64", internal=True)
        self.silent = True

    def stop(self):
        try:
            fd = int(gdb.parse_and_eval("$rdi"))
            buf = int(gdb.parse_and_eval("$rsi"))
            cnt = int(gdb.parse_and_eval("$rdx"))
            off = int(gdb.parse_and_eval("$rcx"))
        except Exception:
            return False
        p = fd_path(fd)
        if cnt < 1024 or "db_storage" not in p:
            return False

        # 先把上一页 dump 掉（此时它已解密完成）
        prev = state["pending"]
        if prev:
            pb, pc, poff, ppath = prev
            try:
                data = inf.read_memory(pb, min(pc, 4096)).tobytes()
                state["n"] += 1
                fn = f"{OUT}/{state['n']:06d}.bin"
                open(fn, "wb").write(data)
                log.write(json.dumps({"file": os.path.basename(fn), "db": ppath,
                                      "offset": poff, "len": len(data),
                                      "head": data[:8].hex()}) + "\n")
            except Exception as e:
                log.write(json.dumps({"err": str(e)}) + "\n")

        state["pending"] = (buf, cnt, off, p)
        return False


class Read(gdb.Breakpoint):
    def __init__(self):
        super().__init__("read", internal=True)
        self.silent = True
    def stop(self):
        try:
            fd = int(gdb.parse_and_eval("$rdi"))
            buf = int(gdb.parse_and_eval("$rsi"))
            cnt = int(gdb.parse_and_eval("$rdx"))
        except Exception:
            return False
        p = fd_path(fd)
        if cnt < 1024 or "db_storage" not in p:
            return False
        prev = state["pending"]
        if prev:
            pb, pc, poff, ppath = prev
            try:
                data = inf.read_memory(pb, min(pc, 4096)).tobytes()
                state["n"] += 1
                fn = f"{OUT}/{state['n']:06d}.bin"
                open(fn, "wb").write(data)
                log.write(json.dumps({"file": os.path.basename(fn), "db": ppath,
                                      "offset": poff, "len": len(data),
                                      "head": data[:8].hex()}) + "\n")
            except Exception:
                pass
        state["pending"] = (buf, cnt, -1, p)
        return False

try:
    gdb.execute("starti")      # 先启动，等动态链接器把 libc 加载进来
except gdb.error:
    pass
Pread()
Read()
log.write(json.dumps({"started": True}) + "\n")
try:
    gdb.execute("continue")
finally:
    prev = state["pending"]
    if prev:
        pb, pc, poff, ppath = prev
        try:
            data = inf.read_memory(pb, min(pc, 4096)).tobytes()
            state["n"] += 1
            fn = f"{OUT}/{state['n']:06d}.bin"
            open(fn, "wb").write(data)
            log.write(json.dumps({"file": os.path.basename(fn), "db": ppath,
                                  "offset": poff, "len": len(data),
                                  "head": data[:8].hex()}) + "\n")
        except Exception:
            pass
