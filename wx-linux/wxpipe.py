#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析流水线：定时入库 -> 够一批就分析 -> 出报告"""
import subprocess
import time
from datetime import datetime

PY = "/root/dsh/wx-linux/venv/bin/python"
BASE = "/root/dsh/wx-linux"
LOG = f"{BASE}/logs/pipe.log"


def log(m):
    line = f"{datetime.now():%m-%d %H:%M:%S} {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(script, *args, timeout=240):
    try:
        r = subprocess.run([PY, "-u", f"{BASE}/{script}", *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout or ""
    except subprocess.TimeoutExpired:
        log(f"{script} 超时")
        return ""


if __name__ == "__main__":
    log("流水线启动")
    while True:
        try:
            out = run("wxdb.py")
            added = [l for l in out.splitlines() if l.startswith("新增")]
            if added:
                log("入库: " + added[0])
            rec = run("wxanalyze.py", "--recover")
            if rec:
                log("恢复: " + rec.splitlines()[0] if rec.splitlines() else "")
            a = run("wxanalyze.py", "--once", "--batch", "200", "--min", "30")
            for line in a.splitlines():
                if "批次" in line or "跳过" in line or "去重后" in line:
                    log("分析: " + line)
        except Exception as e:
            log(f"异常 {e!r}")
        time.sleep(300)
