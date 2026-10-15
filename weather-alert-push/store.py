#!/usr/bin/env python3
"""状态存储（SQLite）：记录已处理/已推送的预警，实现去重与变更检测。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from util import now_str


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                alertid     TEXT PRIMARY KEY,
                fingerprint TEXT,          -- 归一化地区 + "|" + 类型（用于升级/续报检测）
                region      TEXT,
                agency      TEXT,
                type        TEXT,
                level       TEXT,
                title       TEXT,
                issuetime   TEXT,
                url         TEXT,
                first_seen  TEXT,
                last_seen   TEXT,
                status      TEXT,          -- active / gone
                pushed      INTEGER DEFAULT 0,
                push_kind   TEXT           -- 新发布 / 升级 / 降级 / 续报 / 解除
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_fp ON alerts(fingerprint)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON alerts(status)")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        self.conn.commit()

    # ---- meta ----
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ---- alerts ----
    def is_pushed(self, alertid: str) -> bool:
        row = self.conn.execute(
            "SELECT pushed FROM alerts WHERE alertid=?", (alertid,)
        ).fetchone()
        return bool(row and row["pushed"])

    def get(self, alertid: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM alerts WHERE alertid=?", (alertid,)
        ).fetchone()

    def last_pushed_for_fingerprint(self, fingerprint: str) -> sqlite3.Row | None:
        """同一（地区+类型）最近一次已推送记录，用于级别变化判断。"""
        return self.conn.execute(
            "SELECT * FROM alerts WHERE fingerprint=? AND pushed=1 "
            "ORDER BY last_seen DESC LIMIT 1",
            (fingerprint,),
        ).fetchone()

    def active_alertids(self) -> set[str]:
        rows = self.conn.execute(
            "SELECT alertid FROM alerts WHERE status='active'"
        ).fetchall()
        return {r["alertid"] for r in rows}

    def upsert_seen(self, alert: dict):
        """记录一条已见到的现行预警（去重后首次插入；重复则更新 last_seen）。"""
        now = now_str()
        self.conn.execute(
            """
            INSERT INTO alerts(alertid, fingerprint, region, agency, type, level,
                               title, issuetime, url, first_seen, last_seen, status, pushed)
            VALUES(:alertid, :fingerprint, :region, :agency, :type, :level,
                   :title, :issuetime, :url, :first_seen, :last_seen, 'active', 0)
            ON CONFLICT(alertid) DO UPDATE SET last_seen=excluded.last_seen, status='active'
            """,
            {
                "alertid": alert["alertid"],
                "fingerprint": alert["fingerprint"],
                "region": alert.get("region", ""),
                "agency": alert.get("agency", ""),
                "type": alert.get("type", ""),
                "level": alert.get("level", ""),
                "title": alert.get("title", ""),
                "issuetime": alert.get("issuetime", ""),
                "url": alert.get("url", ""),
                "first_seen": now,
                "last_seen": now,
            },
        )
        self.conn.commit()

    def mark_pushed(self, alertid: str, kind: str):
        self.conn.execute(
            "UPDATE alerts SET pushed=1, push_kind=? WHERE alertid=?", (kind, alertid)
        )
        self.conn.commit()

    def mark_gone(self, alertid: str):
        self.conn.execute(
            "UPDATE alerts SET status='gone' WHERE alertid=?", (alertid,)
        )
        self.conn.commit()

    def mark_gone_by_alertid(self, alertid: str):
        self.mark_gone(alertid)

    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass
