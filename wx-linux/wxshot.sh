#!/bin/bash
# 用法: ./wxshot.sh [输出文件]
DISPLAY=:99 import -window root "${1:-/root/dsh/wx-linux/shot.png}" && echo "已截图: ${1:-/root/dsh/wx-linux/shot.png}"
