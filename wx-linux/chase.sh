#!/bin/bash
DB=/home/wxuser/xwechat_files/wxid_REPLACED/db_storage/contact/contact.db
# 后台制造数据库活动：反复点会话、点搜索
( for i in $(seq 1 40); do
    DISPLAY=:99 /root/dsh/wx-linux/venv/bin/python /root/dsh/wx-linux/wxui.py click 400 300 >/dev/null 2>&1
    sleep 1
    DISPLAY=:99 /root/dsh/wx-linux/venv/bin/python /root/dsh/wx-linux/wxui.py click 420 176 >/dev/null 2>&1
    sleep 1
    DISPLAY=:99 /root/dsh/wx-linux/venv/bin/python /root/dsh/wx-linux/wxui.py key esc >/dev/null 2>&1
    sleep 2
  done ) &
for i in $(seq 1 12); do
  PID=$(pgrep -x wechat | head -1)
  OUT=$(/root/dsh/wx-linux/memscan4 $PID "$DB" 2>&1 | tail -3)
  echo "第 $i 轮: $(echo "$OUT" | tr '\n' ' ')"
  echo "$OUT" | grep -q FOUND_KEY && { echo "命中!"; echo "$OUT"; break; }
done
