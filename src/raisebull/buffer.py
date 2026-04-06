"""MessageBuffer — accumulates Discord/LINE channel messages in SQLite.

Messages are stored per channel_key and kept to MAX_BUFFER_SIZE via FIFO eviction.
build_prompt assembles a three-segment prompt: datetime header, earlier messages,
recent messages (within buffer_time_minutes), and the triggering mention text.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import aiosqlite

MAX_BUFFER_SIZE = 200

# Weekday names in Chinese
_WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


class MessageBuffer:
    """Async SQLite-backed per-channel message accumulator."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Open the database connection and create the message_buffer table."""
        self._db = await aiosqlite.connect(self._db_path, timeout=10)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS message_buffer (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_key    TEXT    NOT NULL,
                author         TEXT    NOT NULL,
                content        TEXT    NOT NULL,
                timestamp      REAL    NOT NULL,
                has_attachment INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_buffer_channel_ts
            ON message_buffer (channel_key, timestamp)
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("MessageBuffer.init() has not been awaited")
        return self._db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def insert(
        self,
        channel_key: str,
        author: str,
        content: str,
        timestamp: float,
        has_attachment: bool = False,
    ) -> None:
        """Insert a message and enforce the FIFO MAX_BUFFER_SIZE cap."""
        db = self._require_db()
        await db.execute(
            """
            INSERT INTO message_buffer (channel_key, author, content, timestamp, has_attachment)
            VALUES (?, ?, ?, ?, ?)
            """,
            (channel_key, author, content, timestamp, 1 if has_attachment else 0),
        )
        # FIFO cap: delete oldest rows if count exceeds MAX_BUFFER_SIZE
        await db.execute(
            """
            DELETE FROM message_buffer
            WHERE channel_key = ?
              AND id NOT IN (
                  SELECT id FROM message_buffer
                  WHERE channel_key = ?
                  ORDER BY timestamp DESC
                  LIMIT ?
              )
            """,
            (channel_key, channel_key, MAX_BUFFER_SIZE),
        )
        await db.commit()

    async def get_all(self, channel_key: str) -> list[dict[str, Any]]:
        """Return all messages for channel_key ordered by timestamp ascending."""
        db = self._require_db()
        async with db.execute(
            """
            SELECT channel_key, author, content, timestamp, has_attachment
            FROM message_buffer
            WHERE channel_key = ?
            ORDER BY timestamp ASC
            """,
            (channel_key,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "channel_key": row["channel_key"],
                "author": row["author"],
                "content": row["content"],
                "timestamp": row["timestamp"],
                "has_attachment": bool(row["has_attachment"]),
            }
            for row in rows
        ]

    async def delete_channel(self, channel_key: str) -> None:
        """Delete all messages for channel_key."""
        db = self._require_db()
        await db.execute(
            "DELETE FROM message_buffer WHERE channel_key = ?",
            (channel_key,),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    async def build_prompt(
        self,
        channel_key: str,
        mention_text: str,
        buffer_time_minutes: int = 10,
    ) -> str:
        """Assemble a three-segment prompt for the LLM.

        Segments (joined by \\n\\n---\\n\\n):
          1. Datetime header: 現在時間：YYYY-MM-DD HH:MM (週N)
          2. Earlier conversation (messages older than buffer_time_minutes) — with header
          3. Recent conversation (within buffer_time_minutes) — with header
          4. mention_text
        """
        now_local = datetime.now(timezone.utc).astimezone()
        weekday = _WEEKDAY_ZH[now_local.weekday()]
        datetime_header = now_local.strftime(f"現在時間：%Y-%m-%d %H:%M (週{weekday})")

        rows = await self.get_all(channel_key)
        cutoff = now_local.timestamp() - buffer_time_minutes * 60

        earlier: list[str] = []
        recent: list[str] = []
        for row in rows:
            line = _format_message_line(row)
            if row["timestamp"] < cutoff:
                earlier.append(line)
            else:
                recent.append(line)

        segments: list[str] = [datetime_header]

        if earlier:
            segments.append("【較早的對話】\n" + "\n".join(earlier))

        if recent:
            segments.append("【近期對話】\n" + "\n".join(recent))

        segments.append(mention_text)

        return "\n\n---\n\n".join(segments)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def read_buffer_time(workspace: str) -> int:
        """Read buffer_time (int, minutes) from {workspace}/config/settings.json.

        Returns 10 if the file or key is missing.
        """
        settings_path = os.path.join(workspace, "config", "settings.json")
        try:
            with open(settings_path, encoding="utf-8") as f:
                data = json.load(f)
            return int(data.get("buffer_time", 10))
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
            return 10


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _format_message_line(row: dict[str, Any]) -> str:
    """Format a message row as [HH:MM] Author: Content."""
    ts = row["timestamp"]
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    time_str = dt.strftime("%H:%M")
    return f"[{time_str}] {row['author']}: {row['content']}"
