#!/usr/bin/env python3
"""把截获的明文页写回数据库副本，生成可用 sqlite3 打开的库。"""
import json, os, shutil, sys, sqlite3

meta, outdir = "logs/pages_meta.jsonl", "rebuilt"
os.makedirs(outdir, exist_ok=True)
rows = [json.loads(l) for l in open(meta) if '"file"' in l]
by_db = {}
for r in rows:
    if r["db"].endswith("-wal"):
        continue
    by_db.setdefault(r["db"], []).append(r)

for db, pages in by_db.items():
    name = os.path.basename(db)
    dst = os.path.join(outdir, name)
    shutil.copyfile(db, dst)
    applied = 0
    with open(dst, "r+b") as f:
        for p in pages:
            data = open(f"logs/pages/{p['file']}", "rb").read()
            off = p["offset"]
            if off == 0:
                data = data  # 明文页1 自带 SQLite 头，直接覆盖
            f.seek(off)
            f.write(data[:4096])
            applied += 1
    print(f"{name}: 写回 {applied} 页")
    try:
        con = sqlite3.connect(dst)
        tabs = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table'").fetchall()]
        print(f"   可打开 ✓  表: {tabs[:10]}")
        for t in tabs[:5]:
            try:
                n = con.execute(f"select count(*) from '{t}'").fetchone()[0]
                print(f"     {t}: {n} 行")
            except Exception as e:
                print(f"     {t}: 读取失败 {str(e)[:50]}")
        con.close()
    except Exception as e:
        print(f"   打不开: {e}")
