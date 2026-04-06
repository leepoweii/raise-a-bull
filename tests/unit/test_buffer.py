"""Unit tests for MessageBuffer — SQLite CRUD + three-segment prompt assembly."""
from __future__ import annotations

import json
import pytest
import pytest_asyncio
from time import time

from raisebull.buffer import MessageBuffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ts(offset: float = 0.0) -> float:
    """Return a timestamp relative to now with the given offset in seconds."""
    return time() + offset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def buf(tmp_path):
    db = tmp_path / "buffer_test.db"
    b = MessageBuffer(str(db))
    await b.init()
    yield b
    await b.close()


# ---------------------------------------------------------------------------
# TestBufferCRUD
# ---------------------------------------------------------------------------

class TestBufferCRUD:
    @pytest.mark.asyncio
    async def test_insert_and_get(self, buf):
        await buf.insert("ch1", "Alice", "Hello world", ts())
        rows = await buf.get_all("ch1")
        assert len(rows) == 1
        assert rows[0]["author"] == "Alice"
        assert rows[0]["content"] == "Hello world"
        assert rows[0]["has_attachment"] is False

    @pytest.mark.asyncio
    async def test_get_empty(self, buf):
        rows = await buf.get_all("nonexistent")
        assert rows == []

    @pytest.mark.asyncio
    async def test_delete_channel(self, buf):
        await buf.insert("ch1", "Alice", "msg1", ts())
        await buf.insert("ch1", "Bob", "msg2", ts())
        await buf.delete_channel("ch1")
        rows = await buf.get_all("ch1")
        assert rows == []

    @pytest.mark.asyncio
    async def test_delete_only_target_channel(self, buf):
        await buf.insert("ch1", "Alice", "msg1", ts())
        await buf.insert("ch2", "Bob", "msg2", ts())
        await buf.delete_channel("ch1")
        assert await buf.get_all("ch1") == []
        assert len(await buf.get_all("ch2")) == 1

    @pytest.mark.asyncio
    async def test_insert_with_attachment(self, buf):
        await buf.insert("ch1", "Alice", "see attachment", ts(), has_attachment=True)
        rows = await buf.get_all("ch1")
        assert rows[0]["has_attachment"] is True

    @pytest.mark.asyncio
    async def test_messages_ordered_by_timestamp(self, buf):
        now = ts()
        await buf.insert("ch1", "Alice", "first", now)
        await buf.insert("ch1", "Bob", "second", now + 1)
        await buf.insert("ch1", "Carol", "third", now + 2)
        rows = await buf.get_all("ch1")
        assert [r["content"] for r in rows] == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_buffer_cap_fifo(self, buf):
        """Insert 210 messages — only the 200 most recent should remain."""
        now = ts()
        for i in range(210):
            await buf.insert("ch1", "Bot", f"msg-{i}", now + i)
        rows = await buf.get_all("ch1")
        assert len(rows) == 200
        # Oldest 10 should have been evicted (msg-0 … msg-9)
        contents = [r["content"] for r in rows]
        assert "msg-0" not in contents
        assert "msg-9" not in contents
        assert "msg-10" in contents
        assert "msg-209" in contents


# ---------------------------------------------------------------------------
# TestPromptAssembly
# ---------------------------------------------------------------------------

class TestPromptAssembly:
    @pytest.mark.asyncio
    async def test_build_prompt_with_both_segments(self, buf):
        """Old + recent messages produce two labelled sections."""
        now = ts()
        # old message: 20 minutes ago
        await buf.insert("ch1", "Alice", "old message", now - 20 * 60)
        # recent message: 2 minutes ago
        await buf.insert("ch1", "Bob", "new message", now - 2 * 60)
        prompt = await buf.build_prompt("ch1", "Hey @bot", buffer_time_minutes=10)
        assert "old message" in prompt
        assert "new message" in prompt
        # Both segment headers should appear
        assert "---" in prompt

    @pytest.mark.asyncio
    async def test_build_prompt_recent_only(self, buf):
        """When all messages are recent, only recent segment appears."""
        now = ts()
        await buf.insert("ch1", "Alice", "fresh msg", now - 60)
        prompt = await buf.build_prompt("ch1", "ping", buffer_time_minutes=10)
        assert "fresh msg" in prompt
        assert "ping" in prompt

    @pytest.mark.asyncio
    async def test_build_prompt_empty_buffer(self, buf):
        """Empty buffer still produces a prompt with the mention text."""
        prompt = await buf.build_prompt("ch1", "hello bot", buffer_time_minutes=10)
        assert "hello bot" in prompt

    @pytest.mark.asyncio
    async def test_build_prompt_datetime_header(self, buf):
        """Prompt must start with the 現在時間 datetime header."""
        prompt = await buf.build_prompt("ch1", "test", buffer_time_minutes=10)
        assert prompt.startswith("現在時間：")

    @pytest.mark.asyncio
    async def test_build_prompt_timestamp_per_message(self, buf):
        """Each message line must include a [HH:MM] timestamp."""
        now = ts()
        await buf.insert("ch1", "Alice", "checking format", now - 60)
        prompt = await buf.build_prompt("ch1", "ok", buffer_time_minutes=10)
        # At least one [HH:MM] pattern should appear
        import re
        assert re.search(r"\[\d{2}:\d{2}\]", prompt), "Expected [HH:MM] in prompt"


# ---------------------------------------------------------------------------
# TestReadBufferTime
# ---------------------------------------------------------------------------

class TestReadBufferTime:
    def test_reads_from_settings_json(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(json.dumps({"buffer_time": 15}))
        result = MessageBuffer.read_buffer_time(str(tmp_path))
        assert result == 15

    def test_default_when_file_missing(self, tmp_path):
        result = MessageBuffer.read_buffer_time(str(tmp_path))
        assert result == 10

    def test_default_when_key_missing(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(json.dumps({"other_key": 99}))
        result = MessageBuffer.read_buffer_time(str(tmp_path))
        assert result == 10
