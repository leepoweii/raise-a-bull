"""Integration tests for Web Chat API."""
import json
import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock
from httpx import AsyncClient, ASGITransport

from raisebull.admin import create_admin_app
from raisebull.admin.credentials_db import init_credentials_db
from raisebull.runner import ClaudeRunner, RunResult
from raisebull.session import SessionStore
from raisebull.trace import TraceStep


@pytest.fixture
def mock_runner():
    runner = MagicMock(spec=ClaudeRunner)
    runner.model = "MiniMax-M2.7"
    runner.workspace = "/tmp/ws"

    async def fake_run(prompt, session_id=None, on_trace=None, timeout_seconds=120.0):
        if on_trace:
            await on_trace(TraceStep("thinking", "Let me think..."))
            await on_trace(TraceStep("text", "Here is the answer."))
        return RunResult(
            text="Here is the answer.",
            session_id="claude-sess-123",
            input_tokens=100,
            output_tokens=50,
        )

    runner.run = AsyncMock(side_effect=fake_run)
    return runner


@pytest_asyncio.fixture
async def mock_sessions(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    await store.init()
    yield store
    await store.close()


@pytest.fixture(autouse=True)
def clear_web_sessions():
    from raisebull.admin.routes_chat import _web_sessions
    _web_sessions.clear()
    yield
    _web_sessions.clear()


@pytest.fixture
def chat_app(tmp_path, monkeypatch, mock_runner, mock_sessions):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for d in ("context", "skills", "heartbeat", "config"):
        (workspace / d).mkdir()
    db_path = str(tmp_path / "credentials.db")
    init_credentials_db(db_path)
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")
    app = create_admin_app(
        db_path=db_path,
        workspace_dir=str(workspace),
        runner=mock_runner,
        sessions=mock_sessions,
    )
    return app


@pytest_asyncio.fixture
async def client(chat_app):
    async with AsyncClient(
        transport=ASGITransport(app=chat_app),
        base_url="http://test",
    ) as c:
        await c.post("/api/auth", json={"password": "testpass123"})
        yield c


class TestChatSessions:
    @pytest.mark.asyncio
    async def test_create_session(self, client):
        resp = await client.post("/api/chat/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["id"].startswith("web:")

    @pytest.mark.asyncio
    async def test_list_sessions(self, client):
        await client.post("/api/chat/sessions")
        await client.post("/api/chat/sessions")
        resp = await client.get("/api/chat/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_delete_session(self, client, mock_sessions):
        resp = await client.post("/api/chat/sessions")
        sid = resp.json()["id"]
        resp = await client.delete(f"/api/chat/{sid}")
        assert resp.json()["ok"] is True
        resp = await client.get("/api/chat/sessions")
        ids = [s["id"] for s in resp.json()]
        assert sid not in ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/chat/web:nonexistent")
        assert resp.status_code == 404


class TestChatMessages:
    @pytest.mark.asyncio
    async def test_send_message_sse(self, client):
        resp = await client.post("/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/api/chat/{sid}/messages",
            json={"content": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        types = [e["type"] for e in events]
        assert "thinking" in types
        assert "text" in types
        assert "done" in types

    @pytest.mark.asyncio
    async def test_send_message_to_nonexistent_session(self, client):
        resp = await client.post(
            "/api/chat/web:nonexistent/messages",
            json={"content": "Hello"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_session_persists_to_store(self, client, mock_sessions):
        resp = await client.post("/api/chat/sessions")
        sid = resp.json()["id"]

        await client.post(
            f"/api/chat/{sid}/messages",
            json={"content": "Hello"},
            headers={"Accept": "text/event-stream"},
        )

        row = await mock_sessions.get(sid)
        assert row is not None
        assert row["session_id"] == "claude-sess-123"
        assert row["token_count"] == 150

    @pytest.mark.asyncio
    async def test_send_message_stale_session_recovery(self, client, mock_sessions, mock_runner):
        resp = await client.post("/api/chat/sessions")
        sid = resp.json()["id"]

        await mock_sessions.save(sid, session_id="stale-id", domain="web", token_count=0)

        call_count = [0]
        async def fake_run_stale(prompt, session_id=None, on_trace=None, timeout_seconds=120.0):
            call_count[0] += 1
            if call_count[0] == 1 and session_id == "stale-id":
                return RunResult(error="No conversation found", stale_session=True)
            if on_trace:
                await on_trace(TraceStep("text", "Recovered!"))
            return RunResult(text="Recovered!", session_id="new-sess", input_tokens=10, output_tokens=5)

        mock_runner.run = AsyncMock(side_effect=fake_run_stale)

        resp = await client.post(
            f"/api/chat/{sid}/messages",
            json={"content": "Hello"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        events = [json.loads(line[6:]) for line in resp.text.split("\n") if line.startswith("data: ")]
        types = [e["type"] for e in events]
        assert "text" in types
        assert "done" in types
        row = await mock_sessions.get(sid)
        assert row["session_id"] == "new-sess"
