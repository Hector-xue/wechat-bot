import gdb, json, os

OUT = "/root/dsh/wx-linux/logs/pages"
META = "/root/dsh/wx-linux/logs/pages_meta.jsonl"
os.makedirs(OUT, exist_ok=True)
log = open(META, "a", buffering=1)
state = {"pending": None, "n": 0}

def fd_path(fd):
    try:
        pid = gdb.selected_inferior().pid
        return os.readlink(f"/proc/{pid}/fd/{fd}")
    except Exception:
        return ""

def dump_pending(inf):
    p = state["pending"]
    if not p:
        return
    buf, cnt, off, path = p
    state["pending"] = None
    try:
        data = inf.read_memory(buf, min(cnt, 4096)).tobytes()
        state["n"] += 1
        fn = f"{OUT}/{state['n']:06d}.bin"
        open(fn, "wb").write(data)
        log.write(json.dumps({"file": os.path.basename(fn), "db": path,
                              "offset": off, "len": len(data),
                              "head": data[:8].hex()}) + "\n")
    except Exception as e:
        log.write(json.dumps({"err": str(e)}) + "\n")

def on_stop(ev):
    try:
        rax = int(gdb.parse_and_eval("$rax"))
    except Exception:
        return
    inf = gdb.selected_inferior()
    if rax == 17:                      # pread64 入口
        try:
            fd = int(gdb.parse_and_eval("$rdi")); buf = int(gdb.parse_and_eval("$rsi"))
            cnt = int(gdb.parse_and_eval("$rdx")); off = int(gdb.parse_and_eval("$r10"))
        except Exception:
            return
        p = fd_path(fd)
        dump_pending(inf)
        if "db_storage" in p and cnt >= 1024:
            state["pending"] = (buf, cnt, off, p)
    else:
        dump_pending(inf)

gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.events.stop.connect(on_stop)
try:
    gdb.execute("catch syscall pread64")
except gdb.error:
    pass
log.write(json.dumps({"armed": True}) + "\n")
try:
    gdb.execute("run")
except gdb.error:
    pass
