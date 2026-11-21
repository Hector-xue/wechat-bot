import gdb, json, os

OUT = "/root/dsh/wx-linux/logs/pages"
META = "/root/dsh/wx-linux/logs/pages_meta.jsonl"
os.makedirs(OUT, exist_ok=True)
state = {"pending": None, "n": 0, "hits": 0}
log = open(META, "a", buffering=1)

def fd_path(fd):
    try:
        return os.readlink(f"/proc/{gdb.selected_inferior().pid}/fd/{fd}")
    except Exception:
        return ""

def dump(inf):
    p = state["pending"]
    if not p: return
    buf, cnt, off, path = p
    state["pending"] = None
    try:
        data = inf.read_memory(buf, min(cnt, 4096)).tobytes()
        state["n"] += 1
        fn = f"{OUT}/{state['n']:06d}.bin"
        open(fn, "wb").write(data)
        log.write(json.dumps({"file": os.path.basename(fn), "db": path,
                              "offset": off, "head": data[:8].hex()}) + "\n")
    except Exception as e:
        log.write(json.dumps({"err": str(e)}) + "\n")

def on_syscall():
    inf = gdb.selected_inferior()
    state["hits"] += 1
    try:
        buf = int(gdb.parse_and_eval("$rsi"))
        cnt = int(gdb.parse_and_eval("$rdx"))
    except Exception:
        return
    dump(inf)
    if cnt >= 1024:
        try:
            fd = int(gdb.parse_and_eval("$rdi"))
            off = int(gdb.parse_and_eval("$r10"))
        except Exception:
            return
        p = fd_path(fd)
        if "db_storage" in p:
            state["pending"] = (buf, cnt, off, p)
