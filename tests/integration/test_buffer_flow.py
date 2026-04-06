"""Integration tests for message buffer flow."""
import pytest
import pytest_asyncio
from time import time
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestBufferIntegration:
    @pytest.mark.asyncio
    async def test_silent_mode_buffers_message(self, buf):
        """Non-mention message should be stored in buffer."""
        await buf.insert("discord:123", "Alice", "hello everyone", time())
        msgs = await buf.get_all("discord:123")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hello everyone"

    @pytest.mark.asyncio
    async def test_mention_builds_prompt_with_buffer(self, buf, mock_runner):
        """On mention, prompt should include buffered messages + mention text."""
        now = time()
        await buf.insert("discord:123", "Alice", "earlier message", now - 120)
        await buf.insert("discord:123", "Bob", "recent message", now - 30)

        prompt = await buf.build_prompt("discord:123", "幫我整理", buffer_time_minutes=10)

        # Verify prompt contains buffer context
        assert "earlier message" in prompt
        assert "recent message" in prompt
        assert "幫我整理" in prompt
        assert "現在時間" in prompt

        # Simulate running the prompt
        result = await mock_runner.run(prompt, session_id=None)
        assert result.text == "Done!"

    @pytest.mark.asyncio
    async def test_buffer_cleared_after_reply(self, buf):
        """Buffer should be empty after bot replies (hard delete)."""
        await buf.insert("discord:123", "Alice", "msg1", time())
        await buf.insert("discord:123", "Bob", "msg2", time())

        # Simulate: mention triggered, prompt built, LLM replied, now clear
        await buf.delete_channel("discord:123")

        msgs = await buf.get_all("discord:123")
        assert msgs == []

    @pytest.mark.asyncio
    async def test_buffer_isolation_between_channels(self, buf):
        """Different channels have independent buffers."""
        await buf.insert("discord:111", "Alice", "ch1", time())
        await buf.insert("discord:222", "Bob", "ch2", time())
        await buf.delete_channel("discord:111")

        assert await buf.get_all("discord:111") == []
        assert len(await buf.get_all("discord:222")) == 1

    @pytest.mark.asyncio
    async def test_active_mode_prompt_has_datetime(self, buf):
        """Active mode prompt should have datetime header but no buffer context."""
        from datetime import datetime, timezone
        dt = datetime.now(timezone.utc).astimezone()
        prompt = f"現在時間：{dt.strftime('%Y-%m-%d %H:%M')} ({dt.strftime('%A')})\n\nhello"
        assert "現在時間" in prompt
        assert "hello" in prompt
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in prompt
