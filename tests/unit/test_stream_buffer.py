"""Unit tests for coalescing StreamBuffer."""
import asyncio
import pytest
from raisebull.stream_buffer import CoalesceConfig, StreamBuffer


@pytest.fixture
def sent_messages():
    """Collects messages sent/edited by the buffer."""
    return []


@pytest.fixture
def config():
    return CoalesceConfig(min_chars=50, idle_ms=100, max_chars=200)


def make_buffer(config, sent_messages):
    """Create a StreamBuffer with mock send/edit functions."""
    message_ids = [0]

    class FakeMessage:
        def __init__(self, content, msg_id):
            self.content = content
            self.id = msg_id

        async def edit(self, content: str):
            self.content = content
            sent_messages.append(("edit", self.id, content))

    async def send_fn(text: str) -> FakeMessage:
        message_ids[0] += 1
        msg = FakeMessage(text, message_ids[0])
        sent_messages.append(("send", msg.id, text))
        return msg

    return StreamBuffer(config=config, send_fn=send_fn)


class TestCoalescing:
    @pytest.mark.asyncio
    async def test_small_text_not_flushed_immediately(self, config, sent_messages):
        buf = make_buffer(config, sent_messages)
        await buf.append("hello")
        assert sent_messages == []

    @pytest.mark.asyncio
    async def test_flush_at_min_chars(self, config, sent_messages):
        buf = make_buffer(config, sent_messages)
        await buf.append("x" * 60)
        assert len(sent_messages) == 1
        assert sent_messages[0][0] == "send"

    @pytest.mark.asyncio
    async def test_edit_existing_message(self, config, sent_messages):
        buf = make_buffer(config, sent_messages)
        await buf.append("x" * 60)
        await buf.append("y" * 60)
        assert sent_messages[-1][0] == "edit"
        assert sent_messages[-1][1] == 1

    @pytest.mark.asyncio
    async def test_new_message_at_max_chars(self, config, sent_messages):
        buf = make_buffer(config, sent_messages)
        await buf.append("a" * 60)
        await buf.append("b" * 60)
        await buf.append("c" * 100)
        sends = [m for m in sent_messages if m[0] == "send"]
        assert len(sends) == 2

    @pytest.mark.asyncio
    async def test_finalize_flushes_remaining(self, config, sent_messages):
        buf = make_buffer(config, sent_messages)
        await buf.append("small")
        assert sent_messages == []
        await buf.finalize()
        assert len(sent_messages) == 1
        assert "small" in sent_messages[0][2]

    @pytest.mark.asyncio
    async def test_finalize_empty_buffer_no_op(self, config, sent_messages):
        buf = make_buffer(config, sent_messages)
        await buf.finalize()
        assert sent_messages == []

    @pytest.mark.asyncio
    async def test_idle_timeout_flushes(self, config, sent_messages):
        buf = make_buffer(config, sent_messages)
        await buf.append("hello")
        assert sent_messages == []
        await asyncio.sleep(0.15)
        await buf.check_idle()
        assert len(sent_messages) == 1
