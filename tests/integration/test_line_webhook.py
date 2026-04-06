"""Integration tests for LINE webhook endpoint.

Tests:
- HTTP-level: signature verification (real FastAPI + WebhookParser)
- Handler-level: buffer behavior (direct handler calls with mock events)
"""
import hashlib
import hmac
import base64
import json
import time

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport

from raisebull.runner import RunResult
from raisebull.buffer import MessageBuffer


TEST_CHANNEL_SECRET = "test_secret_for_hmac_signing"


def _sign(body: str, secret: str = TEST_CHANNEL_SECRET) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    ).decode()


def _build_webhook_body(text: str = "hello") -> str:
    return json.dumps({
        "destination": "test",
        "events": [{
            "type": "message",
            "message": {"type": "text", "id": "999", "text": text},
            "timestamp": int(time.time() * 1000),
            "source": {"type": "user", "userId": "Utest"},
            "replyToken": "token",
            "mode": "active",
            "webhookEventId": "evt-1",
            "deliveryContext": {"isRedelivery": False},
        }],
    })


@pytest_asyncio.fixture
async def signature_client(tmp_path, monkeypatch):
    """Minimal FastAPI app for testing webhook signature only."""
    monkeypatch.setenv("LINE_CHANNEL_SECRET", TEST_CHANNEL_SECRET)
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "test")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("WORKSPACE", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_PASSWORD", "test")

    (tmp_path / "workspace").mkdir(exist_ok=True)
    for d in ("config", "skills", "heartbeat", "context"):
        (tmp_path / "workspace" / d).mkdir(exist_ok=True)

    from fastapi import FastAPI, Request, Response, HTTPException
    from linebot.v3 import WebhookParser
    from linebot.v3.exceptions import InvalidSignatureError
    import os

    test_app = FastAPI()

    @test_app.post("/webhook/line")
    async def webhook(request: Request) -> Response:
        body = (await request.body()).decode("utf-8")
        sig = request.headers.get("X-Line-Signature", "")
        if not sig:
            raise HTTPException(status_code=400, detail="Missing X-Line-Signature header")
        parser = WebhookParser(os.getenv("LINE_CHANNEL_SECRET", ""))
        try:
            parser.parse(body, sig)
        except InvalidSignatureError:
            raise HTTPException(status_code=400, detail="Invalid signature")
        return Response(content="OK", status_code=200)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def buf(tmp_path):
    b = MessageBuffer(str(tmp_path / "buf.db"))
    await b.init()
    yield b
    await b.close()


class TestLineWebhookSignature:
    @pytest.mark.asyncio
    async def test_missing_signature_returns_400(self, signature_client):
        resp = await signature_client.post("/webhook/line", content="{}")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_400(self, signature_client):
        body = _build_webhook_body()
        resp = await signature_client.post(
            "/webhook/line", content=body,
            headers={"X-Line-Signature": "bad"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_valid_signature_returns_200(self, signature_client):
        body = _build_webhook_body()
        resp = await signature_client.post(
            "/webhook/line", content=body,
            headers={"X-Line-Signature": _sign(body)},
        )
        assert resp.status_code == 200


class TestLineWebhookHandlerBuffer:
    """Test handle_line_message directly with mock LINE event objects."""

    def _make_event(self, text, source_type="group", group_id="Gabc", user_id="U123"):
        event = MagicMock()
        event.source.type = source_type
        event.source.user_id = user_id
        if source_type == "group":
            event.source.group_id = group_id
        event.message.text = text
        event.message.mention = None
        event.reply_token = "token"
        return event

    def _make_runner(self):
        runner = MagicMock()
        runner.workspace = "/tmp/ws"
        runner.run = AsyncMock(return_value=RunResult(
            text="OK", session_id="s1", input_tokens=50, output_tokens=25,
        ))
        return runner

    def _make_sessions(self):
        sessions = MagicMock()
        sessions.get = AsyncMock(return_value=None)
        sessions.save = AsyncMock()
        return sessions

    @pytest.mark.asyncio
    async def test_group_no_trigger_buffers_only(self, buf):
        """Group message without prefix → buffer INSERT, no LLM."""
        from raisebull.webhook_line import handle_line_message

        event = self._make_event("普通訊息")
        runner = self._make_runner()
        sessions = self._make_sessions()
        messaging_api = MagicMock()

        await handle_line_message(event, runner, sessions, messaging_api, buffer=buf)

        msgs = await buf.get_all("line:group:Gabc")
        assert len(msgs) == 1
        assert "普通訊息" in msgs[0]["content"]
        runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_group_prefix_triggers_and_clears(self, buf):
        """Group message with '小牛兒' prefix → LLM called, buffer cleared."""
        from raisebull.webhook_line import handle_line_message
        from unittest.mock import patch

        # Pre-fill buffer
        await buf.insert("line:group:Gabc", "Uother", "earlier context", time.time() - 60)

        event = self._make_event("小牛兒 幫我整理")
        runner = self._make_runner()
        sessions = self._make_sessions()
        sessions.get = AsyncMock(return_value={"session_id": "old", "token_count": 100})
        messaging_api = MagicMock()
        messaging_api.reply_message = MagicMock()

        with patch("raisebull.webhook_line._read_trigger_prefix", return_value="小牛兒"):
            await handle_line_message(event, runner, sessions, messaging_api, buffer=buf)

        # Buffer should be cleared
        msgs = await buf.get_all("line:group:Gabc")
        assert len(msgs) == 0

    @pytest.mark.asyncio
    async def test_dm_always_responds(self, buf):
        """DM → always responds, no buffer."""
        from raisebull.webhook_line import handle_line_message

        event = self._make_event("你好", source_type="user", user_id="U123")
        runner = self._make_runner()
        sessions = self._make_sessions()
        messaging_api = MagicMock()
        messaging_api.reply_message = MagicMock()
        messaging_api.show_loading_animation = MagicMock()

        await handle_line_message(event, runner, sessions, messaging_api, buffer=buf)

        # DM should not touch buffer
        msgs = await buf.get_all("line:U123")
        assert len(msgs) == 0

    @pytest.mark.asyncio
    async def test_multiple_messages_accumulate_in_buffer(self, buf):
        """Multiple non-trigger messages accumulate."""
        from raisebull.webhook_line import handle_line_message

        runner = self._make_runner()
        sessions = self._make_sessions()
        messaging_api = MagicMock()

        for text in ["第一條", "第二條", "第三條"]:
            event = self._make_event(text)
            await handle_line_message(event, runner, sessions, messaging_api, buffer=buf)

        msgs = await buf.get_all("line:group:Gabc")
        assert len(msgs) == 3
        runner.run.assert_not_called()
