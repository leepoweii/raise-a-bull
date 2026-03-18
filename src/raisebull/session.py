"""Session store for Samantha v2.

Tracks claude -p session IDs per Discord channel or LINE user.
Key format: discord:{channel_id} or line:{user_id}
"""
from __future__ import annotations

import aiosqlite
from datetime import datetime, timezone
from typing import Optional


class SessionStore:
    """Async SQLite-backed session store."""

    def __init__(self, db_path: str = "sessions.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the database connection and create the sessions table if it does not exist."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                key         TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                domain      TEXT NOT NULL,
                last_active TEXT NOT NULL,
                token_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None


    def _require_db(self) -> "aiosqlite.Connection":
        if self._db is None:
            raise RuntimeError("SessionStore.init() has not been awaited")
        return self._db

    async def get(self, key: str) -> Optional[dict]:
        """Return session data for *key*, or None if not found."""
        async with self._require_db().execute(
            "SELECT key, session_id, domain, last_active, token_count "
            "FROM sessions WHERE key = ?",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    async def save(
        self,
        key: str,
        *,
        session_id: str,
        domain: str,
        token_count: int,
    ) -> None:
        """Insert or replace a session record."""
        last_active = datetime.now(timezone.utc).isoformat()
        await self._require_db().execute(
            """
            INSERT OR REPLACE INTO sessions
                (key, session_id, domain, last_active, token_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (key, session_id, domain, last_active, token_count),
        )
        await self._require_db().commit()

    async def clear(self, key: str) -> None:
        """Delete the session for *key* (no-op if not found)."""
        await self._require_db().execute("DELETE FROM sessions WHERE key = ?", (key,))
        await self._require_db().commit()

    async def update_tokens(self, key: str, count: int) -> None:
        """Set token_count for *key* and refresh last_active.

        Raises KeyError if *key* does not exist.
        """
        last_active = datetime.now(timezone.utc).isoformat()
        cursor = await self._require_db().execute(
            "UPDATE sessions SET token_count = ?, last_active = ? WHERE key = ?",
            (count, last_active, key),
        )
        await self._require_db().commit()
        if cursor.rowcount == 0:
            raise KeyError(f"No session for key {key!r}")
