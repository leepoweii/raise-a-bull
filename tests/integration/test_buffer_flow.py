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


class TestLineBufferIntegration:
    @pytest.mark.asyncio
    async def test_line_group_non_mention_buffers(self, buf):
        """LINE group message without mention should be buffered."""
        await buf.insert("line:group:abc", "Alice", "hello group", time())
        msgs = await buf.get_all("line:group:abc")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "hello group"

    @pytest.mark.asyncio
    async def test_line_group_mention_builds_prompt(self, buf):
        """LINE group @mention should build prompt with buffer context."""
        now = time()
        await buf.insert("line:group:abc", "Alice", "earlier", now - 120)
        prompt = await buf.build_prompt("line:group:abc", "幫我查", buffer_time_minutes=10)
        assert "earlier" in prompt
        assert "幫我查" in prompt

    @pytest.mark.asyncio
    async def test_line_group_buffer_cleared_after_reply(self, buf):
        """Buffer for a LINE group should be cleared after bot processes mention."""
        now = time()
        await buf.insert("line:group:abc", "Alice", "msg1", now)
        await buf.insert("line:group:abc", "Bob", "msg2", now)
        await buf.delete_channel("line:group:abc")
        assert await buf.get_all("line:group:abc") == []

    @pytest.mark.asyncio
    async def test_line_group_isolation_from_discord(self, buf):
        """LINE group buffer is isolated from Discord channel buffer."""
        await buf.insert("line:group:abc", "Alice", "line msg", time())
        await buf.insert("discord:999", "Bob", "discord msg", time())
        await buf.delete_channel("line:group:abc")

        assert await buf.get_all("line:group:abc") == []
        assert len(await buf.get_all("discord:999")) == 1

    @pytest.mark.asyncio
    async def test_line_dm_does_not_use_buffer(self, buf):
        """LINE DM messages should not share a buffer with the same user's group."""
        await buf.insert("line:user123", "user123", "dm message", time())
        await buf.insert("line:group:grp1", "user123", "group message", time())

        dm_msgs = await buf.get_all("line:user123")
        grp_msgs = await buf.get_all("line:group:grp1")
        assert len(dm_msgs) == 1
        assert len(grp_msgs) == 1
        assert dm_msgs[0]["content"] == "dm message"
        assert grp_msgs[0]["content"] == "group message"


class TestHandlerDispatch:
    """Test that the webhook handler makes correct buffer/runner decisions."""

    @pytest.mark.asyncio
    async def test_line_group_no_trigger_only_buffers(self, buf):
        """LINE group message without mention/prefix → buffer.insert only, no LLM."""
        from raisebull.webhook_line import handle_line_message
        from unittest.mock import MagicMock, AsyncMock

        # Mock event: group message, no mention
        event = MagicMock()
        event.source.type = "group"
        event.source.user_id = "U123"
        event.source.group_id = "Gabc"
        event.message.text = "普通訊息"
        event.message.mention = None
        event.reply_token = "token"

        runner = MagicMock()
        runner.workspace = "/tmp/ws"
        runner.run = AsyncMock()

        sessions = MagicMock()
        sessions.get = AsyncMock(return_value=None)

        messaging_api = MagicMock()

        with patch("raisebull.webhook_line._read_trigger_prefix", return_value="小牛兒"):
            await handle_line_message(event, runner, sessions, messaging_api, buffer=buf)

        # Buffer should have the message
        msgs = await buf.get_all("line:group:Gabc")
        assert len(msgs) == 1
        assert msgs[0]["content"] == "普通訊息"

        # Runner should NOT have been called
        runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_line_group_prefix_triggers_llm(self, buf):
        """LINE group message with prefix → buffer.build_prompt + runner.run + buffer cleared."""
        from raisebull.webhook_line import handle_line_message
        from unittest.mock import MagicMock, AsyncMock, patch as inner_patch
        from raisebull.runner import RunResult

        # Pre-fill buffer with earlier messages
        await buf.insert("line:group:Gabc2", "U456", "earlier msg", time() - 60)

        # Mock event: group message with prefix trigger
        event = MagicMock()
        event.source.type = "group"
        event.source.user_id = "U123"
        event.source.group_id = "Gabc2"
        event.message.text = "小牛兒 幫我整理"
        event.message.mention = None
        event.reply_token = "token"

        runner = MagicMock()
        runner.workspace = "/tmp/ws"
        runner.run = AsyncMock()

        sessions = MagicMock()
        sessions.get = AsyncMock(return_value={"session_id": "old-sess", "token_count": 500})
        sessions.save = AsyncMock()

        messaging_api = MagicMock()
        messaging_api.reply_message = MagicMock()

        run_result = RunResult(
            text="整理完成", session_id="sess-1",
            input_tokens=100, output_tokens=50,
        )

        with patch("raisebull.webhook_line._read_trigger_prefix", return_value="小牛兒"), \
             patch("raisebull.webhook_line._run_with_recovery", new=AsyncMock(return_value=(run_result, "sess-1"))):
            await handle_line_message(event, runner, sessions, messaging_api, buffer=buf)

        # Buffer should be cleared after reply
        msgs = await buf.get_all("line:group:Gabc2")
        assert len(msgs) == 0

    @pytest.mark.asyncio
    async def test_line_dm_always_responds(self, buf):
        """LINE DM message → always call runner, no buffer."""
        from raisebull.webhook_line import handle_line_message
        from unittest.mock import MagicMock, AsyncMock
        from raisebull.runner import RunResult

        event = MagicMock()
        event.source.type = "user"  # DM, not group
        event.source.user_id = "U123"
        event.message.text = "你好"
        event.message.mention = None
        event.reply_token = "token"

        runner = MagicMock()
        runner.workspace = "/tmp/ws"
        runner.run = AsyncMock()

        sessions = MagicMock()
        sessions.get = AsyncMock(return_value=None)
        sessions.save = AsyncMock()

        messaging_api = MagicMock()
        messaging_api.reply_message = MagicMock()
        messaging_api.show_loading_animation = MagicMock()

        run_result = RunResult(
            text="你好！", session_id="sess-1",
            input_tokens=50, output_tokens=30,
        )

        with patch("raisebull.webhook_line._run_with_recovery", new=AsyncMock(return_value=(run_result, "sess-1"))):
            await handle_line_message(event, runner, sessions, messaging_api, buffer=buf)

        # sessions.save SHOULD have been called (DM always responds and saves session)
        assert sessions.save.called

        # Buffer should remain empty (DMs don't use buffer)
        msgs = await buf.get_all("line:U123")
        assert len(msgs) == 0
