#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
登录一完成就立刻抓数据库密钥，然后直接开库。
=============================================
判据：SQLCipher4 第 1 页，密文从偏移 16 开始，IV 取页尾保留区 4016..4032，
解密后前 6 字节应为 10 00 01 01 50 40（页大小 4096 / 版本 1,1 / 保留区 80）。
再用 HMAC 复核，避免误判。
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DBDIR = "/home/wxuser/xwechat_files/wxid_REPLACED/db_storage"
sys.path.insert(0, str(HERE / "wd"))
from key_scan_common import verify_enc_key  # noqa: E402


def log(m):
    print(f"{time.strftime('%H:%M:%S')} {m}", flush=True)


def brightness():
    subprocess.run(["import", "-window", "root", "/tmp/b.png"],
                   env={"DISPLAY": ":99"}, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = subprocess.run(["convert", "/tmp/b.png", "-colorspace", "Gray",
                          "-format", "%[fx:mean]", "info:"],
                         capture_output=True, text=True).stdout
    try:
        return float(out)
    except ValueError:
        return 0.0


def main():
    log("等待登录完成…")
    while True:
        pids = subprocess.run(["pgrep", "-x", "wechat"], capture_output=True,
                              text=True).stdout.split()
        if pids and brightness() > 0.25:
            break
        time.sleep(3)

    pid = pids[0]
    log(f"检测到已登录 PID={pid}，等 6 秒让数据库打开")
    time.sleep(6)

    page1 = open(f"{DBDIR}/contact/contact.db", "rb").read(4096)
    for attempt in range(6):
        r = subprocess.run([str(HERE / "memscan3"), pid,
                            f"{DBDIR}/contact/contact.db"],
                           capture_output=True, text=True)
        m = re.search(r"FOUND_KEY=([0-9a-f]{64})", r.stdout)
        if m and verify_enc_key(bytes.fromhex(m.group(1)), page1):
            key = m.group(1)
            log(f"✅ 密钥到手: {key}")
            (HERE / "dbkey.json").write_text(json.dumps({"contact": key}))
            return key
        log(f"第 {attempt+1} 轮没命中，5 秒后重试（可能数据库刚打开）")
        time.sleep(5)
    log("❌ 多轮扫描仍未命中")
    return None


if __name__ == "__main__":
    k = main()
    if k:
        import sqlcipher3
        con = sqlcipher3.connect(f"{DBDIR}/contact/contact.db")
        con.execute(f"PRAGMA key = \"x'{k}'\"")
        n = con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        log(f"开库验证: sqlite_master 有 {n[0]} 个对象")
        try:
            rows = con.execute("SELECT count(*) FROM contact").fetchone()
            log(f"contact 表 {rows[0]} 行")
        except Exception as e:
            log(f"contact 查询: {e}")
