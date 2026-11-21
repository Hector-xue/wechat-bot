import sqlcipher3, os, subprocess, sys, time
KEY = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
db = "/tmp/sanity.db"
for f in (db, db+"-wal", db+"-shm"):
    if os.path.exists(f): os.remove(f)
con = sqlcipher3.connect(db)
con.execute(f"PRAGMA key = \"x'{KEY}'\"")
con.execute("CREATE TABLE t(a)")
con.execute("INSERT INTO t VALUES('hello')")
con.commit(); con.close()
print("建库完成, 页大小=", os.path.getsize(db), "倍数4096=", os.path.getsize(db)%4096)
# 起一个装着这个 key 的进程
code = f"import time; k=bytes.fromhex('{KEY}'); time.sleep(120)"
p = subprocess.Popen([sys.executable, "-c", code])
print("持有 key 的进程 PID=", p.pid)
open("/tmp/sanity.pid","w").write(str(p.pid))
