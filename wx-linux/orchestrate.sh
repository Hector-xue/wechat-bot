#!/bin/bash
cd /root/dsh/wx-linux
# 1) 清空旧捕获
rm -rf logs/pages; mkdir -p logs/pages; rm -f logs/pages_meta.jsonl
# 2) 重启微信
pgrep -x wechat | xargs -r kill; sleep 3
su - wxuser -c 'cd /opt/wechat && DISPLAY=:99 XDG_RUNTIME_DIR=/tmp/runtime-wx setsid nohup ./wechat >>/home/wxuser/wechat.log 2>&1 &'
sleep 6
PID=$(pgrep -x wechat | head -1)
echo "wechat pid=$PID  等待登录…"
# 3) 立刻挂捕获（登录过程中的读盘都会被记录）
nohup gdb -q -batch -p $PID -x gdbpage2.py >/dev/null 2>&1 &
GDBPID=$!
# 4) 等登录完成（亮度 > 0.25）
for i in $(seq 1 60); do
  B=$(DISPLAY=:99 import -window root /tmp/b2.png 2>/dev/null && convert /tmp/b2.png -colorspace Gray -format "%[fx:mean]" info: 2>/dev/null)
  OK=$(awk -v b="${B:-0}" 'BEGIN{print (b>0.25)?"y":"n"}')
  [ "$OK" = "y" ] && { echo "已登录 (第 $((i*4))s)"; break; }
  sleep 4
done
sleep 8
# 5) 登录完成后点开会话并滚动
venv/bin/python drive_capture.py >/dev/null 2>&1
sleep 3
kill $GDBPID 2>/dev/null
echo "捕获页数: $(ls logs/pages 2>/dev/null | wc -l)"
