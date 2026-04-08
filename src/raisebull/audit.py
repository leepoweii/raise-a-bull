"""Append-only audit log backed by SQLite.

Lifecycle mirrors SessionStore: construct with db_path, await init() to
open connection + create table, await close() to release connection.
The audit_log table lives in the same sessions.db file as SessionStore
and MessageBuffer — each class holds its own aiosqlite connection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import aiosqlite


class AuditLog:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the connection and create the audit_log table + indexes."""
        self._db = await aiosqlite.connect(self._db_path, timeout=10)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                actor       TEXT NOT NULL,
                action      TEXT NOT NULL,
                target      TEXT,
                before_val  TEXT,
                after_val   TEXT,
                source_ip   TEXT
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts DESC)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)"
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _require_db(self) -> "aiosqlite.Connection":
        if self._db is None:
            raise RuntimeError("AuditLog.init() has not been awaited")
        return self._db

    async def record(
        self,
        action: str,
        *,
        actor: str = "system",
        target: Optional[str] = None,
        before_val: Optional[str] = None,
        after_val: Optional[str] = None,
        source_ip: Optional[str] = None,
    ) -> None:
        """Append one audit row. Timestamp is generated now (UTC ISO 8601)."""
        ts = datetime.now(timezone.utc).isoformat()
        await self._require_db().execute(
            """
            INSERT INTO audit_log
                (ts, actor, action, target, before_val, after_val, source_ip)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, actor, action, target, before_val, after_val, source_ip),
        )
        await self._require_db().commit()

    async def list_recent(
        self,
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return rows matching the date range, newest first.

        from_ts / to_ts are ISO 8601 strings. Pass `limit + 1` from the
        caller to detect truncation.
        """
        async with self._require_db().execute(
            """
            SELECT id, ts, actor, action, target, before_val, after_val, source_ip
            FROM audit_log
            WHERE (? IS NULL OR ts >= ?)
              AND (? IS NULL OR ts <= ?)
            ORDER BY ts DESC
            LIMIT ?
            """,
            (from_ts, from_ts, to_ts, to_ts, limit),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
