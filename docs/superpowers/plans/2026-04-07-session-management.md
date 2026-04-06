# Session Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add message buffering for Discord/LINE channels (buffer → @mention → three-segment prompt), session history display in dashboard (read .jsonl), heartbeat fresh start, and nightly compact + consolidate.

**Architecture:** New `MessageBuffer` class handles SQLite CRUD for buffered messages. Discord/LINE bots accumulate messages in silent mode, assemble three-segment prompts on @mention, and hard-delete buffer after reply. Per-channel `asyncio.Lock` serializes LLM calls. Dashboard reads Claude Code's `.jsonl` files for history display. Nightly job compacts eligible sessions and consolidates learnings into memory files.

**Tech Stack:** SQLite (aiosqlite), asyncio.Lock, Claude Code .jsonl parsing, APScheduler

**Spec:** `docs/superpowers/specs/2026-04-06-session-management-design.md`

---

## Sub-Phase Structure

This plan is split into 3 independent sub-phases, each producing deployable software:

| Sub-phase | Tasks | What it delivers | Depends on |
|-----------|-------|-------------------|------------|
| **SP1: Buffer + Discord + LINE** | 1, 2, 3, 4 | Discord/LINE buffer + @mention trigger + three-segment prompt | None |
| **SP2: History API + Chat UI** | 5, 6 | Dashboard shows full conversation history from .jsonl | None (independent) |
| **SP3: Heartbeat + Nightly Compact** | 7, 8, 9, 10 | Heartbeat fresh start + nightly compact/consolidate | SP1 (buffer needed for compact inject) |

**Execute order:** SP1 first (most urgent pain point), then SP2 (can parallel), then SP3 (after SP1 stable).

Each sub-phase ends with: all tests pass → push → deploy → verify on samantha-wsl.

### SP1 Checkpoint (after Task 4)
- Run: `uv run pytest tests/unit/ tests/integration/ -q`
- Push + rebuild on samantha-wsl
- Verify: send messages in Discord channel → @mention → bot responds with buffer context

### SP2 Checkpoint (after Task 6)
- Run: `uv run pytest tests/unit/ tests/integration/ -q`
- Push + rebuild on samantha-wsl
- Verify: click any session in dashboard → conversation history loads

### SP3 Checkpoint (after Task 10)
- Run: `uv run pytest tests/unit/ tests/integration/ -q` + smoke tests
- Push + rebuild on samantha-wsl
- Verify: heartbeat no longer accumulates tokens + nightly job runs

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `src/raisebull/buffer.py` | MessageBuffer class: SQLite CRUD + three-segment prompt assembly |
| `tests/unit/test_buffer.py` | Buffer CRUD, prompt assembly, datetime injection |
| `tests/unit/test_line_mention.py` | LINE @mention detection (is_self) |
| `tests/integration/test_buffer_flow.py` | Full buffer → mention → prompt flow + LINE regression |
| `tests/integration/test_history.py` | History API endpoint tests |

### Modified files
| File | Changes |
|------|---------|
| `src/raisebull/session.py` | Add message_buffer table + last_compacted_at migration |
| `src/raisebull/discord_bot.py` | Per-channel lock, buffer INSERT in silent mode, prompt assembly on mention, active mode direct |
| `src/raisebull/webhook_line.py` | @mention detection, buffer for group chats, DM unchanged |
| `src/raisebull/main.py` | LINE webhook: route non-mention group messages to buffer |
| `src/raisebull/heartbeat.py` | Fresh start (no resume), nightly compact job |
| `src/raisebull/admin/routes_chat.py` | History API endpoint |
| `src/raisebull/admin/routes_settings.py` | Add buffer_time, nightly_compact_hour to _ALLOWED_KEYS |
| `src/raisebull/admin/static/pages/chat.js` | Load history on session select |
| `workspace.example/config/settings.json` | Add new setting defaults |

---

---

# SP1: Buffer + Discord + LINE (Tasks 1–4)

---

## Task 1: MessageBuffer Module + Unit Tests

**Files:**
- Create: `src/raisebull/buffer.py`
- Create: `tests/unit/test_buffer.py`
- Modify: `src/raisebull/session.py` (add table migration)

This is the foundation — a standalone module with no dependencies on Discord/LINE.

- [ ] **Step 1: Write failing tests for buffer CRUD**

Create `tests/unit/test_buffer.py`:

```python
"""Unit tests for message buffer."""
import pytest
import pytest_asyncio
from time import time
from raisebull.buffer import MessageBuffer


@pytest_asyncio.fixture
async def buf(tmp_path):
    b = MessageBuffer(str(tmp_path / "test.db"))
    await b.init()
    yield b
    await b.close()


class TestBufferCRUD:
    @pytest.mark.asyncio
    async def test_insert_and_get(self, buf):
        await buf.insert("discord:123", "Alice", "Hello", time())
        msgs = await buf.get_all("discord:123")
        assert len(msgs) == 1
        assert msgs[0]["author"] == "Alice"
        assert msgs[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_get_empty(self, buf):
        msgs = await buf.get_all("discord:999")
        assert msgs == []

    @pytest.mark.asyncio
    async def test_delete_channel(self, buf):
        await buf.insert("discord:123", "Alice", "msg1", time())
        await buf.insert("discord:123", "Bob", "msg2", time())
        await buf.delete_channel("discord:123")
        msgs = await buf.get_all("discord:123")
        assert msgs == []

    @pytest.mark.asyncio
    async def test_delete_only_target_channel(self, buf):
        await buf.insert("discord:123", "Alice", "keep", time())
        await buf.insert("discord:456", "Bob", "delete", time())
        await buf.delete_channel("discord:456")
        msgs = await buf.get_all("discord:123")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "keep"

    @pytest.mark.asyncio
    async def test_insert_with_attachment(self, buf):
        await buf.insert("discord:123", "Alice", "(附件: /path/to/file.txt)", time(), has_attachment=True)
        msgs = await buf.get_all("discord:123")
        assert msgs[0]["has_attachment"] == 1

    @pytest.mark.asyncio
    async def test_messages_ordered_by_timestamp(self, buf):
        t = time()
        await buf.insert("ch", "Bob", "second", t + 1)
        await buf.insert("ch", "Alice", "first", t)
        msgs = await buf.get_all("ch")
        assert msgs[0]["author"] == "Alice"
        assert msgs[1]["author"] == "Bob"


class TestPromptAssembly:
    @pytest.mark.asyncio
    async def test_build_prompt_with_both_segments(self, buf):
        now = time()
        await buf.insert("ch", "Alice", "old message", now - 700)  # 11+ min ago
        await buf.insert("ch", "Bob", "recent message", now - 60)  # 1 min ago
        prompt = await buf.build_prompt("ch", "幫我整理", buffer_time_minutes=10)
        assert "old message" in prompt
        assert "recent message" in prompt
        assert "幫我整理" in prompt
        assert "現在時間" in prompt

    @pytest.mark.asyncio
    async def test_build_prompt_recent_only(self, buf):
        now = time()
        await buf.insert("ch", "Alice", "just now", now - 30)
        prompt = await buf.build_prompt("ch", "OK", buffer_time_minutes=10)
        assert "just now" in prompt
        assert "稍早" not in prompt  # no "earlier" section

    @pytest.mark.asyncio
    async def test_build_prompt_empty_buffer(self, buf):
        prompt = await buf.build_prompt("ch", "hello", buffer_time_minutes=10)
        assert "hello" in prompt
        assert "現在時間" in prompt

    @pytest.mark.asyncio
    async def test_build_prompt_datetime_header(self, buf):
        prompt = await buf.build_prompt("ch", "test", buffer_time_minutes=10)
        # Should start with datetime line
        assert prompt.startswith("現在時間：")

    @pytest.mark.asyncio
    async def test_build_prompt_timestamp_per_message(self, buf):
        await buf.insert("ch", "Alice", "hi", time() - 30)
        prompt = await buf.build_prompt("ch", "test", buffer_time_minutes=10)
        # Each message line should have [HH:MM] timestamp
        assert "[" in prompt  # timestamp bracket
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && uv run pytest tests/unit/test_buffer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'raisebull.buffer'`

- [ ] **Step 3: Implement buffer.py**

Create `src/raisebull/buffer.py`:

```python
"""Message buffer — accumulates channel messages for context injection on @mention."""

import aiosqlite
from datetime import datetime, timezone
from time import time as _time
from typing import Optional


class MessageBuffer:
    """Async SQLite-backed message buffer. One table, shared DB with SessionStore."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path, timeout=10)  # prevent SQLITE_BUSY under concurrent writes
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS message_buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_key TEXT NOT NULL,
                author TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL,
                has_attachment INTEGER DEFAULT 0
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_buffer_channel ON message_buffer(channel_key)"
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("MessageBuffer.init() has not been awaited")
        return self._db

    async def insert(
        self, channel_key: str, author: str, content: str,
        timestamp: float, has_attachment: bool = False,
    ) -> None:
        await self._require_db().execute(
            "INSERT INTO message_buffer (channel_key, author, content, timestamp, has_attachment) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel_key, author, content, timestamp, int(has_attachment)),
        )
        await self._require_db().commit()

    async def get_all(self, channel_key: str) -> list[dict]:
        async with self._require_db().execute(
            "SELECT id, channel_key, author, content, timestamp, has_attachment "
            "FROM message_buffer WHERE channel_key = ? ORDER BY timestamp",
            (channel_key,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def delete_channel(self, channel_key: str) -> None:
        await self._require_db().execute(
            "DELETE FROM message_buffer WHERE channel_key = ?", (channel_key,),
        )
        await self._require_db().commit()

    async def build_prompt(
        self, channel_key: str, mention_text: str,
        buffer_time_minutes: int = 10,
    ) -> str:
        """Assemble three-segment prompt from buffer + mention text.

        Returns prompt string with:
        1. Datetime header
        2. Earlier conversation (older than buffer_time)
        3. Recent conversation (within buffer_time)
        4. User mention text
        """
        now = _time()
        cutoff = now - buffer_time_minutes * 60
        msgs = await self.get_all(channel_key)

        # Datetime header
        dt = datetime.now(timezone.utc).astimezone()
        weekday = dt.strftime("%A")
        header = f"現在時間：{dt.strftime('%Y-%m-%d %H:%M')} ({weekday})"

        earlier = [m for m in msgs if m["timestamp"] < cutoff]
        recent = [m for m in msgs if m["timestamp"] >= cutoff]

        def fmt_msg(m: dict) -> str:
            t = datetime.fromtimestamp(m["timestamp"]).strftime("%H:%M")
            return f"[{t}] {m['author']}: {m['content']}"

        parts = [header]

        if earlier:
            lines = "\n".join(fmt_msg(m) for m in earlier)
            parts.append(f"以下是頻道稍早的對話：\n{lines}")

        if recent:
            label = f"以下是最近 {buffer_time_minutes} 分鐘的對話：" if earlier else "以下是頻道近期的對話："
            lines = "\n".join(fmt_msg(m) for m in recent)
            parts.append(f"{label}\n{lines}")

        parts.append(f"用戶提到你：\n{mention_text}")

        return "\n\n---\n\n".join(parts)
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/unit/test_buffer.py -v`
Expected: all PASS

- [ ] **Step 5: Add migration to SessionStore + update get() SELECT**

In `src/raisebull/session.py`:

**5a.** Add `last_compacted_at` migration after the `name` migration (inside `init()`). Also set `timeout=10` on the aiosqlite connection to prevent `SQLITE_BUSY` under concurrent writes:

```python
        # Migration: add last_compacted_at column if missing
        try:
            await self._db.execute("ALTER TABLE sessions ADD COLUMN last_compacted_at TEXT")
        except Exception:
            pass
```

And update `SessionStore.__init__` or `init()` to open the connection with `timeout=10`:

```python
    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._db_path, timeout=10)
        ...
```

**5b.** Update the `get()` method's SELECT query to include `last_compacted_at` (currently at line 57–59):

Change:
```python
"SELECT key, session_id, domain, last_active, token_count, name "
```

To:
```python
"SELECT key, session_id, domain, last_active, token_count, name, last_compacted_at "
```

Without this fix, `nightly_compact()` → `is_compact_eligible()` will get a `KeyError` on `row["last_compacted_at"]` even after the column is added.

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/unit/ tests/integration/ -q`
Expected: all pass (existing + new)

- [ ] **Step 7: Commit**

```bash
git add src/raisebull/buffer.py src/raisebull/session.py tests/unit/test_buffer.py
git commit -m "feat: MessageBuffer module (SQLite CRUD + three-segment prompt assembly)"
```

---

## Task 2: Settings (buffer_time, nightly_compact_hour)

**Files:**
- Modify: `src/raisebull/admin/routes_settings.py`
- Modify: `workspace.example/config/settings.json`

- [ ] **Step 1: Add new settings to _ALLOWED_KEYS**

In `src/raisebull/admin/routes_settings.py`, add to `_ALLOWED_KEYS` dict:

```python
    "buffer_time": ("10", "BUFFER_TIME"),
    "nightly_compact_hour": ("3", "NIGHTLY_COMPACT_HOUR"),
```

- [ ] **Step 2: Update workspace.example defaults**

In `workspace.example/config/settings.json`, add:

```json
{
  "agent_name": "Agent",
  "model": "MiniMax-M2.7",
  "max_steps": "100",
  "auto_reply_timeout": "180",
  "session_idle_timeout": "1800",
  "heartbeat_interval": "1800",
  "buffer_time": "10",
  "nightly_compact_hour": "3"
}
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/integration/test_admin.py::TestSettings -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/raisebull/admin/routes_settings.py workspace.example/config/settings.json
git commit -m "feat: add buffer_time + nightly_compact_hour settings"
```

---

## Task 3: Discord Buffer Integration

**Files:**
- Modify: `src/raisebull/discord_bot.py`
- Create: `tests/integration/test_buffer_flow.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/integration/test_buffer_flow.py`:

```python
"""Integration tests for message buffer flow."""
import pytest
import pytest_asyncio
from time import time
from unittest.mock import MagicMock, AsyncMock

from raisebull.buffer import MessageBuffer
from raisebull.runner import RunResult


@pytest_asyncio.fixture
async def buf(tmp_path):
    b = MessageBuffer(str(tmp_path / "buffer.db"))
    await b.init()
    yield b
    await b.close()


@pytest.fixture
def mock_runner():
    runner = MagicMock()
    runner.workspace = "/tmp/ws"
    runner.model = "MiniMax-M2.7"
    runner.run = AsyncMock(return_value=RunResult(
        text="Done!", session_id="sess-1", input_tokens=100, output_tokens=50,
    ))
    return runner


class TestBufferPromptFlow:
    @pytest.mark.asyncio
    async def test_mention_includes_buffer_context(self, buf, mock_runner):
        """Buffer messages appear in the prompt sent to runner."""
        now = time()
        await buf.insert("discord:123", "Alice", "earlier msg", now - 700)
        await buf.insert("discord:123", "Bob", "recent msg", now - 30)

        prompt = await buf.build_prompt("discord:123", "幫我整理", buffer_time_minutes=10)

        assert "earlier msg" in prompt
        assert "recent msg" in prompt
        assert "幫我整理" in prompt
        assert "現在時間" in prompt

    @pytest.mark.asyncio
    async def test_buffer_cleared_after_reply(self, buf):
        """Buffer is hard-deleted after bot replies."""
        await buf.insert("discord:123", "Alice", "msg1", time())
        await buf.insert("discord:123", "Bob", "msg2", time())

        # Simulate: bot replied → delete
        await buf.delete_channel("discord:123")

        msgs = await buf.get_all("discord:123")
        assert msgs == []

    @pytest.mark.asyncio
    async def test_empty_buffer_mention(self, buf):
        """Mention with empty buffer still produces valid prompt."""
        prompt = await buf.build_prompt("discord:123", "hello", buffer_time_minutes=10)
        assert "hello" in prompt
        assert "現在時間" in prompt

    @pytest.mark.asyncio
    async def test_buffer_isolation_between_channels(self, buf):
        """Different channels have independent buffers."""
        await buf.insert("discord:111", "Alice", "ch1 msg", time())
        await buf.insert("discord:222", "Bob", "ch2 msg", time())

        msgs1 = await buf.get_all("discord:111")
        msgs2 = await buf.get_all("discord:222")
        assert len(msgs1) == 1
        assert len(msgs2) == 1
        assert msgs1[0]["content"] == "ch1 msg"

    @pytest.mark.asyncio
    async def test_prompt_datetime_is_current(self, buf):
        """Prompt datetime should be approximately now."""
        from datetime import datetime
        prompt = await buf.build_prompt("ch", "test", buffer_time_minutes=10)
        # Extract year from prompt
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in prompt
```

- [ ] **Step 2: Run tests — verify they fail (import OK, tests should pass since buffer module exists)**

Run: `uv run pytest tests/integration/test_buffer_flow.py -v`
Expected: all PASS (these test the buffer module integration)

- [ ] **Step 3: Modify discord_bot.py**

Read the full file first. Key changes:

**Add imports** at top:
```python
import asyncio as _asyncio
from raisebull.buffer import MessageBuffer
```

**Add per-channel locks and buffer** inside `create_bot()` (after `channel_states` dict):
```python
    _channel_locks: dict[str, _asyncio.Lock] = {}
    _message_buffer: MessageBuffer | None = None

    def _get_lock(key: str) -> _asyncio.Lock:
        if key not in _channel_locks:
            _channel_locks[key] = _asyncio.Lock()
        return _channel_locks[key]
```

**Add buffer init** in `on_ready`:
```python
    @bot.event
    async def on_ready() -> None:
        nonlocal _message_buffer
        # Init message buffer (shares DB with sessions)
        db_path = os.environ.get("DB_PATH", "/app/workspace/data/sessions.db")
        _message_buffer = MessageBuffer(db_path)
        await _message_buffer.init()
        # ... existing guild sync code ...
```

> **Startup race condition note:** `_message_buffer` is `None` from process start until `on_ready` fires (typically a few seconds). Any `on_message` event that arrives in this window will see `_message_buffer is None`. The silent-mode buffer check (`if not should_respond(state, mentioned) and _message_buffer:`) safely skips buffering when `_message_buffer` is None — the message is dropped from the buffer but the bot still responds normally on @mention. This is acceptable behavior during startup.

**Modify `on_message`** — the key logic change:

After `state = channel_states.setdefault(key, ChannelState())` and `mentioned = ...`:

```python
        # Always buffer in silent mode (before should_respond check)
        if not should_respond(state, mentioned) and _message_buffer:
            # Silent mode: accumulate to buffer, no LLM call
            content = message.content
            if bot.user:
                content = content.replace(f"<@{bot.user.id}>", "").strip()
            author = message.author.display_name or message.author.name
            await _message_buffer.insert(key, author, content, time())
            # Also process attachments immediately (parse to workspace)
            for att in message.attachments:
                try:
                    file_bytes = await att.read()
                    filepath, preview = await process_attachment(
                        file_bytes, att.filename, att.content_type or "",
                        session_id=key, workspace=runner.workspace,
                        vision_client=_vision_client,
                    )
                    await _message_buffer.insert(
                        key, author,
                        f"(附件: {filepath} — {preview[:100]})",
                        time(), has_attachment=True,
                    )
                except Exception:
                    logger.exception("Silent mode: attachment processing failed")
            return  # Don't process further in silent mode
```

**On mention — assemble buffer prompt:**

Replace the existing `prompt = message.content` block. When `mentioned` is True:

```python
        # Confirmed response — now mutate state
        if mentioned:
            state.on_mention()
        else:
            state.on_message()

        # Build prompt
        raw_text = message.content
        if bot.user:
            raw_text = raw_text.replace(f"<@{bot.user.id}>", "").strip()
        if not raw_text and not message.attachments:
            raw_text = "Hello"

        # Process attachments (active mode or mention)
        attachment_parts = []
        # ... existing attachment processing code unchanged ...

        if attachment_parts:
            raw_text = "\n\n---\n\n".join(attachment_parts) + "\n\n" + (raw_text or "")
            raw_text = raw_text.strip()

        # If this is a mention (transition from silent), inject buffer context
        if mentioned and _message_buffer:
            # Read settings for buffer_time
            import json
            settings_path = os.path.join(runner.workspace or "/app/workspace", "config", "settings.json")
            buffer_time = 10  # default
            try:
                with open(settings_path) as f:
                    settings = json.load(f)
                    buffer_time = int(settings.get("buffer_time", "10"))
            except Exception:
                pass

            prompt = await _message_buffer.build_prompt(key, raw_text, buffer_time_minutes=buffer_time)
        else:
            # Active mode: direct message with datetime header
            from datetime import datetime, timezone
            dt = datetime.now(timezone.utc).astimezone()
            prompt = f"現在時間：{dt.strftime('%Y-%m-%d %H:%M')} ({dt.strftime('%A')})\n\n{raw_text}"
```

**Wrap LLM call in per-channel lock — the lock must span from session lookup through session save:**

```python
        async with _get_lock(key):
            session = await sessions.get(key)
            session_id = session["session_id"] if session else None
            existing_tokens = session["token_count"] if session else 0

            # ... LLM call (run_with_trace, reply_msg, thread traces, etc.) ...

            await sessions.save(
                key,
                session_id=effective_session_id,
                domain="discord",
                token_count=existing_tokens + new_tokens,
                name=channel_name,
            )
            # After saving session, clear buffer (content is now in .jsonl)
            if mentioned and _message_buffer:
                await _message_buffer.delete_channel(key)
```

The lock scope is critical: it must wrap from session lookup to session save (inclusive). This prevents two concurrent messages from racing to overwrite the session, and ensures buffer.delete_channel() runs only after a successful save.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/unit/ tests/integration/ tests/test_discord_bot.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/discord_bot.py tests/integration/test_buffer_flow.py
git commit -m "feat: Discord message buffer — silent accumulate, mention prompt, per-channel lock"
```

---

## Task 4: LINE Buffer Integration + @mention Detection

**Files:**
- Modify: `src/raisebull/webhook_line.py`
- Modify: `src/raisebull/main.py`
- Create: `tests/unit/test_line_mention.py`

- [ ] **Step 1: Write LINE mention detection tests**

Create `tests/unit/test_line_mention.py`:

```python
"""Unit tests for LINE @mention detection."""
import pytest


def _make_mention(is_self: bool):
    """Create a mock mention object."""
    class Mentionee:
        def __init__(self, is_self):
            self.is_self = is_self
            self.type = "user"
    class Mention:
        def __init__(self, mentionees):
            self.mentionees = mentionees
    return Mention([Mentionee(is_self)])


class TestLineMentionDetection:
    def test_is_self_true(self):
        from raisebull.webhook_line import line_bot_is_mentioned
        mention = _make_mention(is_self=True)
        assert line_bot_is_mentioned(mention) is True

    def test_is_self_false(self):
        from raisebull.webhook_line import line_bot_is_mentioned
        mention = _make_mention(is_self=False)
        assert line_bot_is_mentioned(mention) is False

    def test_no_mention(self):
        from raisebull.webhook_line import line_bot_is_mentioned
        assert line_bot_is_mentioned(None) is False

    def test_empty_mentionees(self):
        from raisebull.webhook_line import line_bot_is_mentioned
        class EmptyMention:
            mentionees = []
        assert line_bot_is_mentioned(EmptyMention()) is False
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/unit/test_line_mention.py -v`
Expected: FAIL — `cannot import name 'line_bot_is_mentioned'`

- [ ] **Step 3: Implement mention detection + buffer in webhook_line.py**

Add `line_bot_is_mentioned()` to `src/raisebull/webhook_line.py`:

```python
def line_bot_is_mentioned(mention) -> bool:
    """Check if bot was @mentioned in a LINE message."""
    if not mention:
        return False
    for m in getattr(mention, "mentionees", []):
        if getattr(m, "is_self", False):
            return True
    return False
```

Modify `handle_line_message()` to accept a `buffer` parameter and add group-chat buffering. Current signature (line 127):

```python
async def handle_line_message(
    event: "MessageEvent",
    runner: "ClaudeRunner",
    sessions: "SessionStore",
    messaging_api: "MessagingApi",
) -> None:
```

New signature:

```python
async def handle_line_message(
    event: "MessageEvent",
    runner: "ClaudeRunner",
    sessions: "SessionStore",
    messaging_api: "MessagingApi",
    buffer: "MessageBuffer | None" = None,
) -> None:
```

New body — add group-chat buffer logic before the existing `_process_message` call:

```python
async def handle_line_message(
    event: "MessageEvent",
    runner: "ClaudeRunner",
    sessions: "SessionStore",
    messaging_api: "MessagingApi",
    buffer: "MessageBuffer | None" = None,
) -> None:
    """Dispatcher: resolve context, handle commands, then process message."""
    user_id: str = event.source.user_id
    session_key, prompt, chat_id = _resolve_context(event)

    # Fast path: Rich Menu commands (no Claude invocation)
    if event.message.text.strip().lower() in _LINE_COMMANDS:
        await _handle_line_command(
            event.message.text, session_key,
            event.reply_token, chat_id, sessions, runner, messaging_api,
        )
        return

    # Group chat buffer logic (DMs always respond directly)
    if event.source.type == "group" and buffer is not None:
        mention = getattr(event.message, "mention", None)
        is_mentioned = line_bot_is_mentioned(mention)

        if not is_mentioned:
            # Silent mode: accumulate to buffer, no LLM call
            author = user_id  # LINE group chat doesn't expose display names without extra API call
            from time import time
            await buffer.insert(session_key, author, event.message.text.strip(), time())
            return

        # Mentioned in group: assemble buffer prompt
        import json, os
        settings_path = os.path.join(runner.workspace or "/app/workspace", "config", "settings.json")
        buffer_time = 10
        try:
            with open(settings_path) as f:
                buffer_time = int(json.load(f).get("buffer_time", "10"))
        except Exception:
            pass
        # Strip the @mention token from the text to get the actual request
        # LINE mention has index + length fields we can use to remove the @BotName part
        raw_text = event.message.text or ""
        if event.message.mention and event.message.mention.mentionees:
            for m in event.message.mention.mentionees:
                if getattr(m, "is_self", False):
                    idx = getattr(m, "index", 0)
                    length = getattr(m, "length", 0)
                    raw_text = (raw_text[:idx] + raw_text[idx + length:]).strip()
                    break
        mention_text = raw_text.strip() or "Hello"
        prompt = await buffer.build_prompt(session_key, mention_text, buffer_time_minutes=buffer_time)

        await _process_message(
            prompt=prompt,
            session_key=session_key,
            chat_id=chat_id,
            user_id=user_id,
            reply_token=event.reply_token,
            runner=runner,
            sessions=sessions,
            messaging_api=messaging_api,
        )
        await buffer.delete_channel(session_key)
        return

    # DM or group without buffer: process directly (unchanged behavior)
    await _process_message(
        prompt=prompt,
        session_key=session_key,
        chat_id=chat_id,
        user_id=user_id,
        reply_token=event.reply_token,
        runner=runner,
        sessions=sessions,
        messaging_api=messaging_api,
    )
```

Key design decisions:
- **DMs always skip buffering** — `source.type != "group"` falls through to existing `_process_message`, no change.
- **Buffer = None fallback** — if buffer isn't initialized yet (startup race, see Issue 9), group messages skip buffering and respond directly (safe degradation).
- **Buffer deleted after reply** — `delete_channel()` called after `_process_message` returns successfully.

- [ ] **Step 4: Update main.py to pass buffer to LINE handlers**

In `main.py` lifespan, add a `_message_buffer` global and initialize it alongside `_sessions`. Also note the startup race condition: `_message_buffer` is `None` until `init()` completes — the `buffer: "MessageBuffer | None" = None` default in `handle_line_message()` provides safe degradation if a LINE event arrives before buffer is ready.

Add global:
```python
_message_buffer: "MessageBuffer | None" = None
```

In the lifespan `async with` block, after `_sessions.init()`:
```python
    from raisebull.buffer import MessageBuffer
    _message_buffer = MessageBuffer(os.getenv("DB_PATH", "/app/data/sessions.db"))
    await _message_buffer.init()
```

Update the LINE webhook handler in `_process()` (currently at line 189) to pass the buffer:

```python
                if isinstance(event.message, TextMessageContent):
                    await handle_line_message(
                        event, _runner, _sessions, messaging_api, buffer=_message_buffer
                    )
```

No change needed for `handle_line_attachment` — attachments in group chats are processed immediately (same as Discord active mode).

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_line_mention.py tests/unit/ tests/integration/ -q`
Expected: all pass

- [ ] **Step 6: Add LINE regression tests to test_buffer_flow.py**

Append to `tests/integration/test_buffer_flow.py`:

```python
class TestLineRegression:
    def test_line_mention_is_self(self):
        from raisebull.webhook_line import line_bot_is_mentioned
        # Simulate is_self=True
        class M:
            mentionees = [type("", (), {"is_self": True})()]
        assert line_bot_is_mentioned(M()) is True

    def test_line_no_mention_returns_false(self):
        from raisebull.webhook_line import line_bot_is_mentioned
        assert line_bot_is_mentioned(None) is False

    def test_line_dm_always_responds(self):
        """DMs should not use buffer — this is a design constraint, not a code test."""
        # This test documents the expected behavior
        # DM detection: source.type != "group"
        pass  # Verified by code review — DM path doesn't check mention
```

- [ ] **Step 7: Commit**

```bash
git add src/raisebull/webhook_line.py src/raisebull/main.py tests/unit/test_line_mention.py tests/integration/test_buffer_flow.py
git commit -m "feat: LINE message buffer — @mention detection, group buffer, DM unchanged"
```

---

# SP2: History API + Chat UI (Tasks 5–6)

---

## Task 5: Session History API

**Files:**
- Modify: `src/raisebull/admin/routes_chat.py`
- Create: `tests/integration/test_history.py`

- [ ] **Step 1: Write failing tests**

Create `tests/integration/test_history.py`:

```python
"""Integration tests for session history API."""
import json
import os
import pytest
import pytest_asyncio
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport

from raisebull.admin import create_admin_app
from raisebull.admin.credentials_db import init_credentials_db
from raisebull.runner import ClaudeRunner
from raisebull.session import SessionStore


@pytest_asyncio.fixture
async def setup(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for d in ("context", "skills", "heartbeat", "config"):
        (workspace / d).mkdir()

    # Create a fake .jsonl file
    claude_dir = tmp_path / "claude_home" / ".claude" / "projects" / "-workspace"
    claude_dir.mkdir(parents=True)
    jsonl = claude_dir / "test-session-id.jsonl"
    jsonl.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "Hello"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Let me think..."}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi there!"}]}}),
    ]) + "\n")

    db_path = str(tmp_path / "credentials.db")
    init_credentials_db(db_path)
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")

    store = SessionStore(str(tmp_path / "sessions.db"))
    await store.init()
    await store.save("web:test", session_id="test-session-id", domain="web", token_count=100)

    runner = MagicMock(spec=ClaudeRunner)
    runner.workspace = str(workspace)

    app = create_admin_app(
        db_path=db_path, workspace_dir=str(workspace),
        runner=runner, sessions=store,
    )
    # Store claude home for the history endpoint to find .jsonl
    app.state.claude_home = str(tmp_path / "claude_home")

    from fastapi import FastAPI
    parent = FastAPI()
    parent.mount("/admin", app)

    async with AsyncClient(
        transport=ASGITransport(app=parent), base_url="http://test",
    ) as client:
        await client.post("/admin/api/auth", json={"password": "testpass123"})
        yield {"client": client, "store": store, "jsonl": jsonl, "claude_dir": claude_dir}

    await store.close()


class TestHistoryAPI:
    @pytest.mark.asyncio
    async def test_returns_parsed_messages(self, setup):
        resp = await setup["client"].get("/admin/api/chat/web:test/history")
        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) >= 2
        user_msgs = [m for m in msgs if m["role"] == "user"]
        asst_msgs = [m for m in msgs if m["role"] == "assistant"]
        assert len(user_msgs) >= 1
        assert user_msgs[0]["content"] == "Hello"

    @pytest.mark.asyncio
    async def test_missing_session_returns_404(self, setup):
        resp = await setup["client"].get("/admin/api/chat/web:nonexistent/history")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_jsonl_returns_empty(self, setup):
        """Session exists in DB but .jsonl was deleted."""
        await setup["store"].save("web:orphan", session_id="no-such-file", domain="web", token_count=0)
        resp = await setup["client"].get("/admin/api/chat/web:orphan/history")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_empty_jsonl_returns_empty(self, setup):
        empty = setup["claude_dir"] / "empty-sess.jsonl"
        empty.write_text("")
        await setup["store"].save("web:empty", session_id="empty-sess", domain="web", token_count=0)
        resp = await setup["client"].get("/admin/api/chat/web:empty/history")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_corrupted_jsonl_skips_bad_lines(self, setup):
        """Corrupted lines in .jsonl are silently skipped; valid lines still returned."""
        corrupted = setup["claude_dir"] / "corrupt-sess.jsonl"
        corrupted.write_text(
            'NOT_JSON_AT_ALL\n'
            + json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "valid line"}]}}) + "\n"
            + '{"truncated": \n'  # malformed JSON
        )
        await setup["store"].save("web:corrupt", session_id="corrupt-sess", domain="web", token_count=0)
        resp = await setup["client"].get("/admin/api/chat/web:corrupt/history")
        assert resp.status_code == 200
        msgs = resp.json()
        assert len(msgs) == 1
        assert msgs[0]["content"] == "valid line"
```

- [ ] **Step 2: Implement history endpoint in routes_chat.py**

Add to `src/raisebull/admin/routes_chat.py`:

```python
import glob

@router.get("/api/chat/{session_id}/history")
async def get_history(session_id: str, request: Request):
    sessions_store = getattr(request.app.state, "sessions", None)
    if not sessions_store:
        return JSONResponse({"error": "no sessions store"}, status_code=503)

    row = await sessions_store.get(session_id)
    if not row:
        return JSONResponse({"error": "session not found"}, status_code=404)

    claude_session_id = row["session_id"]
    claude_home = getattr(request.app.state, "claude_home", None) or os.path.expanduser("~")

    # Find .jsonl file
    jsonl_path = None
    projects_dir = os.path.join(claude_home, ".claude", "projects")
    if os.path.isdir(projects_dir):
        for subdir in os.listdir(projects_dir):
            candidate = os.path.join(projects_dir, subdir, f"{claude_session_id}.jsonl")
            if os.path.isfile(candidate):
                jsonl_path = candidate
                break

    if not jsonl_path or not os.path.isfile(jsonl_path):
        return []

    # Parse JSONL
    messages = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = d.get("type")
                msg = d.get("message", {})
                if not isinstance(msg, dict):
                    continue

                content_blocks = msg.get("content", [])
                if not isinstance(content_blocks, list):
                    continue

                if msg_type == "user":
                    text = ""
                    for block in content_blocks:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text += block.get("text", "")
                    if text:
                        messages.append({"role": "user", "content": text})

                elif msg_type == "assistant":
                    thinking = None
                    text = None
                    tool_calls = []
                    for block in content_blocks:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "thinking":
                            thinking = block.get("thinking", "")
                        elif block.get("type") == "text":
                            text = block.get("text", "")
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "name": block.get("name", ""),
                                "input": block.get("input", {}),
                            })
                    if thinking or text or tool_calls:
                        entry = {"role": "assistant"}
                        if thinking:
                            entry["thinking"] = thinking
                        if text:
                            entry["content"] = text
                        if tool_calls:
                            entry["tool_calls"] = tool_calls
                        messages.append(entry)

                elif msg_type == "tool_result" or (msg_type == "user" and d.get("tool_results")):
                    # Tool results are sometimes nested differently
                    pass

    except (OSError, UnicodeDecodeError):
        pass

    return messages
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/integration/test_history.py -v`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/raisebull/admin/routes_chat.py tests/integration/test_history.py
git commit -m "feat: session history API (read Claude Code .jsonl files)"
```

---

## Task 6: Chat Page History Display

**Files:**
- Modify: `src/raisebull/admin/static/pages/chat.js`

- [ ] **Step 1: Update selectSession to load history**

In `chat.js`, modify `selectSession()`:

```javascript
        async selectSession(sid) {
            this.currentSession = sid;
            const session = this.sessions.find(s => s.id === sid);
            this.currentSessionType = session?.type || 'web';
            this.currentSessionName = session?.name || null;
            this.messages = [];
            this.input = '';
            this.pendingFiles = [];

            // Load conversation history from .jsonl
            try {
                const history = await this.getApp().api(
                    '/api/chat/' + encodeURIComponent(sid) + '/history'
                );
                if (Array.isArray(history)) {
                    for (const msg of history) {
                        this.messages.push(msg);
                    }
                }
            } catch (e) {
                // History unavailable — empty chat is fine
            }
            this.$nextTick(() => this.scrollToBottom());
        },
```

- [ ] **Step 2: Verify by running all tests**

Run: `uv run pytest tests/unit/ tests/integration/ -q`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add src/raisebull/admin/static/pages/chat.js
git commit -m "feat: chat page loads session history from .jsonl on select"
```

---

# SP3: Heartbeat + Nightly Compact (Tasks 7–10)

---

## Task 7: Heartbeat Fresh Start

**Files:**
- Modify: `src/raisebull/heartbeat.py`

- [ ] **Step 1: Change heartbeat to not resume sessions**

In `src/raisebull/heartbeat.py`, modify `_heartbeat_tick()` around line 82:

Change:
```python
    session_id = session["session_id"] if session else None
    # ...
    result = await runner.run(prompt, session_id=session_id, timeout_seconds=600.0)
```

To:
```python
    # Fresh start each tick — no session persistence for heartbeat
    result = await runner.run(prompt, session_id=None, timeout_seconds=600.0)
```

- [ ] **Step 2: Run existing heartbeat tests**

Run: `uv run pytest tests/unit/test_heartbeat_parse.py tests/integration/test_status.py -v`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add src/raisebull/heartbeat.py
git commit -m "fix: heartbeat fresh start — no session resume, prevents token accumulation"
```

---

## Task 8: Nightly Compact + Consolidate

**Files:**
- Modify: `src/raisebull/heartbeat.py`
- Create: `tests/unit/test_nightly_compact.py`

- [ ] **Step 1: Write tests for nightly compact logic**

Create `tests/unit/test_nightly_compact.py`:

```python
"""Unit tests for nightly compact eligibility logic."""
import pytest
from raisebull.heartbeat import is_compact_eligible


class TestCompactEligibility:
    def test_eligible_high_tokens_no_compact(self):
        session = {"token_count": 60000, "last_compacted_at": None, "last_active": "2026-04-07T10:00:00"}
        assert is_compact_eligible(session) is True

    def test_not_eligible_low_tokens(self):
        session = {"token_count": 30000, "last_compacted_at": None, "last_active": "2026-04-07T10:00:00"}
        assert is_compact_eligible(session) is False

    def test_not_eligible_recently_compacted(self):
        session = {
            "token_count": 60000,
            "last_compacted_at": "2026-04-07T02:00:00",
            "last_active": "2026-04-06T10:00:00",  # last_active BEFORE last_compacted
        }
        assert is_compact_eligible(session) is False

    def test_eligible_new_activity_after_compact(self):
        session = {
            "token_count": 60000,
            "last_compacted_at": "2026-04-06T03:00:00",
            "last_active": "2026-04-07T10:00:00",  # last_active AFTER last_compacted
        }
        assert is_compact_eligible(session) is True

    def test_skip_heartbeat_sessions(self):
        """Heartbeat sessions should never be compacted (fresh start each tick)."""
        session = {"token_count": 100000, "last_compacted_at": None, "last_active": "2026-04-07T10:00:00"}
        assert is_compact_eligible(session, key="heartbeat:system") is False
```

- [ ] **Step 2: Add list_all() to SessionStore**

Before implementing `nightly_compact()`, add two methods to `src/raisebull/session.py`:

1. `list_all()` — iterates all sessions (avoids accessing `_require_db()` directly)
2. `update_compacted_at()` — updates `last_compacted_at` timestamp after compact

```python
    async def list_all(self) -> list[dict]:
        """Return all sessions as a list of dicts. Used by nightly compact."""
        async with self._require_db().execute(
            "SELECT key, session_id, domain, last_active, token_count, name, last_compacted_at "
            "FROM sessions"
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def update_compacted_at(self, key: str, timestamp: str) -> None:
        """Set last_compacted_at for a session. Called after nightly compact."""
        await self._require_db().execute(
            "UPDATE sessions SET last_compacted_at = ? WHERE key = ?",
            (timestamp, key),
        )
        await self._require_db().commit()
```

The nightly compact uses `sessions.list_all()` and `sessions.update_compacted_at()` — no direct `_require_db()` access from outside SessionStore.

- [ ] **Step 3: Implement compact eligibility + nightly job**

Add to `src/raisebull/heartbeat.py`:

```python
COMPACT_TOKEN_THRESHOLD = 50_000


def is_compact_eligible(session: dict, key: str = "") -> bool:
    """Check if a session should be compacted in the nightly job."""
    if key.startswith("heartbeat:"):
        return False
    if session["token_count"] < COMPACT_TOKEN_THRESHOLD:
        return False
    last_compacted = session.get("last_compacted_at")
    if last_compacted and session["last_active"] <= last_compacted:
        return False  # No new activity since last compact
    return True
```

Add nightly compact function:

```python
async def nightly_compact(runner: ClaudeRunner, sessions: SessionStore, buffer: "MessageBuffer | None" = None) -> None:
    """Run nightly compact + consolidate. Called by scheduler at configured hour."""
    # Use list_all() — avoids accessing sessions._require_db() directly
    all_sessions = await sessions.list_all()
    eligible = [s for s in all_sessions if is_compact_eligible(s, key=s["key"])]
    if not eligible:
        logger.info("Nightly compact: no eligible sessions")
        return

    for s in eligible:
        key = s["key"]
        session_id = s["session_id"]
        logger.info("Nightly compact: %s (tokens=%d)", key, s["token_count"])

        # Step 1: inject unprocessed buffer into session
        if buffer:
            msgs = await buffer.get_all(key)
            if msgs:
                prompt = await buffer.build_prompt(key, "(nightly compact — injecting buffered messages)")
                await runner.run(prompt, session_id=session_id, timeout_seconds=300.0)
                await buffer.delete_channel(key)

        # Step 2: compact
        result = await runner.run("/compact", session_id=session_id, timeout_seconds=300.0)
        if result.error:
            logger.error("Compact failed for %s: %s", key, result.error)
            continue

        # Step 3: update DB
        now = datetime.now(timezone.utc).isoformat()
        await sessions.update_compacted_at(key, now)

    # Step 4: consolidate — one LLM call to update memory
    summary_parts = []
    for s in eligible:
        summary_parts.append(f"Session {s['key']}: {s['token_count']} tokens")

    consolidate_prompt = (
        "你是記憶整理助理。以下 session 剛剛被 compact 了。\n"
        "請讀取各 session 的最新狀態，整理重要資訊，更新 memory/ 目錄下的相關檔案。\n"
        "你可以自行決定要寫入哪些檔案。\n\n"
        + "\n".join(summary_parts)
    )
    await runner.run(consolidate_prompt, session_id=None, timeout_seconds=600.0)
    logger.info("Nightly consolidate complete")
```

Update `start_heartbeat()` signature in `src/raisebull/heartbeat.py` to accept `buffer` (currently line 110):

Change:
```python
def start_heartbeat(runner: ClaudeRunner, sessions: SessionStore, push_fn=None) -> None:
```

To:
```python
def start_heartbeat(
    runner: ClaudeRunner,
    sessions: SessionStore,
    push_fn=None,
    buffer: "MessageBuffer | None" = None,
) -> None:
```

Register the nightly compact job using APScheduler's native coroutine support (no lambda needed — APScheduler handles async coroutines directly via `AsyncIOScheduler`):

```python
    # Nightly compact job
    compact_hour = int(os.environ.get("NIGHTLY_COMPACT_HOUR", "3"))
    _scheduler.add_job(
        nightly_compact,
        "cron", hour=compact_hour, minute=0,
        args=[runner, sessions, buffer],
        id="nightly_compact",
    )
```

Using `args=[runner, sessions, buffer]` instead of `lambda: asyncio.create_task(...)` fixes two issues: (1) APScheduler's `AsyncIOScheduler` natively awaits coroutine functions, no manual `create_task` needed; (2) avoids the closure-capture footgun where lambda captures variable references rather than values.

Update the caller in `main.py` (currently line 90) to pass the buffer:

Change:
```python
    start_heartbeat(_runner, _sessions, push_fn=_heartbeat_push)
```

To:
```python
    start_heartbeat(_runner, _sessions, push_fn=_heartbeat_push, buffer=_message_buffer)
```

Note: `_message_buffer` must be initialized before `start_heartbeat()` is called. Move the buffer init block to before the `start_heartbeat` call in the lifespan.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_nightly_compact.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/heartbeat.py src/raisebull/session.py tests/unit/test_nightly_compact.py
git commit -m "feat: nightly compact + consolidate (>50K tokens, new activity, skip heartbeat) + list_all()"
```

---

## Task 9: Smoke Tests

**Files:**
- Modify: `tests/smoke/test_smoke.py`

- [ ] **Step 1: Add buffer + history smoke tests**

Append to `tests/smoke/test_smoke.py`:

```python
@smoke
@pytest.mark.asyncio
async def test_buffer_prompt_with_real_llm(runner: ClaudeRunner, tmp_path):
    """Smoke: buffer messages → build prompt → LLM understands context."""
    from raisebull.buffer import MessageBuffer
    from time import time

    buf = MessageBuffer(str(tmp_path / "buf.db"))
    await buf.init()

    now = time()
    await buf.insert("test:ch", "Alice", "今天要討論預算", now - 120)
    await buf.insert("test:ch", "Bob", "預算大約五萬", now - 60)

    prompt = await buf.build_prompt("test:ch", "剛才說的預算是多少？只回答數字。", buffer_time_minutes=10)

    r = ClaudeRunner(
        claude_bin=runner.claude_bin,
        workspace=str(tmp_path),
        model=runner.model,
        mcp_config=runner.mcp_config,
    )
    result = await r.run(prompt, timeout_seconds=60.0)
    assert result.error is None, f"LLM error: {result.error}"
    assert "五萬" in result.text or "50000" in result.text or "5万" in result.text, f"Expected budget in: {result.text}"

    await buf.close()
```

- [ ] **Step 2: Run smoke test**

Run:
```bash
ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic \
ANTHROPIC_AUTH_TOKEN=<key> \
uv run pytest tests/smoke/test_smoke.py::test_buffer_prompt_with_real_llm -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/smoke/test_smoke.py
git commit -m "test: smoke test for buffer prompt → LLM reads context correctly"
```

---

## Task 10: Final Verification + Push + Deploy

- [ ] **Step 1: Run all fast tests**

Run: `uv run pytest tests/unit/ tests/integration/ -v`
Expected: all pass (~175 total)

- [ ] **Step 2: Update CLAUDE.md**

Update test counts and add session management to key decisions.

- [ ] **Step 3: Push**

```bash
git push origin feature/calf-merge
```

- [ ] **Step 4: Deploy to samantha-wsl**

```bash
ssh -p 2222 samantha-machine@samantha-wsl.tail5a1118.ts.net
cd ~/raise-a-bull && git pull origin feature/calf-merge
BOT_NAME=daniu BOT_PORT=18888 BOT_ENV_FILE=~/bots/daniu/.env WORKSPACE_PATH=~/bots/daniu/workspace docker compose build
docker stop bull-daniu && docker rm bull-daniu
BOT_NAME=daniu BOT_PORT=18888 BOT_ENV_FILE=~/bots/daniu/.env WORKSPACE_PATH=~/bots/daniu/workspace docker compose up -d
```
