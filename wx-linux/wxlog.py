#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构化事件记录：收到/回复/异常都落一条"""
import os
import sqlite3
import time

DB = "/root/dsh/wx-linux/events.db"


def _conn():
    con = sqlite3.connect(DB, timeout=5)
    con.execute("""CREATE TABLE IF NOT EXISTS event(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        kind TEXT NOT NULL,          -- recv / reply / error / login
        chat TEXT DEFAULT '',
        text TEXT DEFAULT '',
        latency REAL DEFAULT 0,      -- 消息发出到被感知的秒数
        gen_ms INTEGER DEFAULT 0,    -- LLM 生成耗时
        send_ms INTEGER DEFAULT 0,   -- 发送耗时
        ok INTEGER DEFAULT 1,
        detail TEXT DEFAULT '')""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ts ON event(ts)")
    return con


def event(kind, chat="", text="", latency=0, gen_ms=0, send_ms=0, ok=1, detail=""):
    try:
        con = _conn()
        con.execute(
            "insert into event(ts,kind,chat,text,latency,gen_ms,send_ms,ok,detail)"
            " values(?,?,?,?,?,?,?,?,?)",
            (int(time.time()), kind, chat, (text or "")[:400],
             float(latency or 0), int(gen_ms or 0), int(send_ms or 0),
             1 if ok else 0, (detail or "")[:300]))
        con.commit()
        con.close()
    except Exception:
        pass


def stats(hours=24):
    try:
        con = _conn()
        since = int(time.time()) - hours * 3600
        q = lambda sql, *a: con.execute(sql, a).fetchone()
        recv = q("select count(*) from event where kind='recv' and ts>?", since)[0]
        rep = q("select count(*) from event where kind='reply' and ts>?", since)[0]
        okn = q("select count(*) from event where kind='reply' and ok=1 and ts>?", since)[0]
        lat = q("select avg(latency) from event where kind='recv' and ts>?", since)[0] or 0
        gen = q("select avg(gen_ms) from event where kind='reply' and ts>?", since)[0] or 0
        snd = q("select avg(send_ms) from event where kind='reply' and ts>?", since)[0] or 0
        err = q("select count(*) from event where kind='error' and ts>?", since)[0]
        con.close()
        return {"recv": recv, "reply": rep, "ok": okn, "err": err,
                "avg_latency": round(lat, 1), "avg_gen_ms": int(gen),
                "avg_send_ms": int(snd)}
    except Exception:
        return {"recv": 0, "reply": 0, "ok": 0, "err": 0,
                "avg_latency": 0, "avg_gen_ms": 0, "avg_send_ms": 0}
