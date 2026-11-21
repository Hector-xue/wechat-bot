#!/bin/bash
# 实时守护的启停脚本（避免 pkill 自匹配）
cd /root/dsh/wx-linux
PIDF=logs/rt.pid
case "$1" in
  stop)
    [ -f "$PIDF" ] && kill "$(cat $PIDF)" 2>/dev/null
    rm -f "$PIDF"
    echo stopped
    ;;
  start)
    shift
    setsid nohup venv/bin/python -u wxrealtime.py "$@" > logs/realtime.log 2>&1 &
    echo $! > "$PIDF"
    echo "started $(cat $PIDF)"
    ;;
  status)
    [ -f "$PIDF" ] && kill -0 "$(cat $PIDF)" 2>/dev/null && echo "running $(cat $PIDF)" || echo stopped
    ;;
esac
