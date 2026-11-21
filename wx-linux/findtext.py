import sys, os, glob
needle = sys.argv[1].encode()
hits = []
for f in glob.glob("/root/dsh/wx-linux/logs/pages/*.bin"):
    try:
        data = open(f, "rb").read()
    except OSError:
        continue
    if needle in data:
        hits.append((f, data.find(needle)))
print(f"搜索 {sys.argv[1]!r}: 命中 {len(hits)} 个页")
for f, off in hits[:10]:
    print(f"  {f} offset={off}")
