#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书告警：给主人发消息，带限流防刷屏"""
import json
import os
import subprocess
import time

USER_OPEN_ID = "ou_5a81cf86b88f3ac3d9a75d2d25f3fcc5"
STATE = "/root/dsh/wx-linux/logs/lark_alert_state.json"
PANEL = "http://47.110.181.182:3080/bot/"


def _state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def send(message, key="default", cooldown=3600):
    """按 key 限流：同一种告警 cooldown 秒内只发一次"""
    st = _state()
    if time.time() - st.get(key, 0) < cooldown:
        return False
    try:
        env = dict(os.environ)
        env.setdefault("HOME", "/root")
        r = subprocess.run(
            ["lark-cli", "im", "+messages-send", "--as", "bot",
             "--user-id", USER_OPEN_ID, "--text", message],
            capture_output=True, text=True, timeout=30, env=env)
        ok = ('"ok": true' in (r.stdout or "")) or ('"ok":true' in (r.stdout or ""))
        if ok:
            st[key] = time.time()
            try:
                os.makedirs(os.path.dirname(STATE), exist_ok=True)
                json.dump(st, open(STATE, "w"))
            except OSError:
                pass
        return ok
    except Exception:
        return False


if __name__ == "__main__":
    print("发送测试:", send("微信机器人飞书告警通道已就绪。", key="test", cooldown=0))
