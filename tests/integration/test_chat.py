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
    from fastapi import FastAPI
    parent = FastAPI()
    parent.mount("/admin", chat_app)
    async with AsyncClient(
        transport=ASGITransport(app=parent),
        base_url="http://test",
    ) as c:
        await c.post("/admin/api/auth", json={"password": "testpass123"})
        yield c


class TestChatSessions:
    @pytest.mark.asyncio
    async def test_create_session(self, client):
        resp = await client.post("/admin/api/chat/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["id"].startswith("web:")

    @pytest.mark.asyncio
    async def test_list_sessions(self, client):
        await client.post("/admin/api/chat/sessions")
        await client.post("/admin/api/chat/sessions")
        resp = await client.get("/admin/api/chat/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 2
        session = sessions[0]
        assert "id" in session
        assert "type" in session
        assert session["type"] == "web"
        assert "name" in session  # None or str
        assert "created_at" in session
        assert "message_count" in session
        assert "token_count" in session
        assert isinstance(session["message_count"], int)
        assert isinstance(session["token_count"], int)

    @pytest.mark.asyncio
    async def test_delete_session(self, client, mock_sessions):
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]
        resp = await client.delete(f"/admin/api/chat/{sid}")
        assert resp.json()["ok"] is True
        resp = await client.get("/admin/api/chat/sessions")
        ids = [s["id"] for s in resp.json()]
        assert sid not in ids

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/admin/api/chat/web:nonexistent")
        assert resp.status_code == 404


class TestChatMessages:
    @pytest.mark.asyncio
    async def test_send_message_sse(self, client):
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
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
        done_event = [e for e in events if e["type"] == "done"][0]
        assert "session_id" in done_event
        assert "tokens" in done_event
        assert "in" in done_event["tokens"]
        assert "out" in done_event["tokens"]
        assert "error" in done_event
        assert done_event["error"] is None

    @pytest.mark.asyncio
    async def test_send_message_to_nonexistent_session(self, client):
        resp = await client.post(
            "/admin/api/chat/web:nonexistent/messages",
            json={"content": "Hello"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_session_persists_to_store(self, client, mock_sessions):
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        await client.post(
            f"/admin/api/chat/{sid}/messages",
            json={"content": "Hello"},
            headers={"Accept": "text/event-stream"},
        )

        row = await mock_sessions.get(sid)
        assert row is not None
        assert row["session_id"] == "claude-sess-123"
        assert row["token_count"] == 150

    @pytest.mark.asyncio
    async def test_send_message_stale_session_recovery(self, client, mock_sessions, mock_runner):
        resp = await client.post("/admin/api/chat/sessions")
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
            f"/admin/api/chat/{sid}/messages",
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


class TestChatFileUpload:
    @pytest.mark.asyncio
    async def test_send_message_with_file(self, client, mock_runner, tmp_path):
        """Upload a .txt file → file saved + SSE streams."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            data={"content": ""},
            files={"files": ("test.txt", b"Hello from file", "text/plain")},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        call_args = mock_runner.run.call_args
        prompt = call_args.kwargs.get("prompt") or call_args[0][0]
        assert "test.txt" in prompt
        assert "Read" in prompt

    @pytest.mark.asyncio
    async def test_send_message_with_file_and_text(self, client, mock_runner):
        """Upload file + text → both appear in prompt."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            data={"content": "請分析這個檔案"},
            files={"files": ("data.csv", b"name,age\nAlice,30", "text/csv")},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        call_args = mock_runner.run.call_args
        prompt = call_args.kwargs.get("prompt") or call_args[0][0]
        assert "data.csv" in prompt
        assert "請分析這個檔案" in prompt

    @pytest.mark.asyncio
    async def test_send_message_file_too_large(self, client):
        """File > 10MB → 413."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        big_content = b"x" * (10 * 1024 * 1024 + 1)
        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            data={"content": ""},
            files={"files": ("big.txt", big_content, "text/plain")},
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_send_message_no_content_no_files(self, client):
        """Empty multipart request (no content, no files) → 400."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            data={"content": ""},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_send_message_json_still_works(self, client, mock_runner):
        """JSON body without files → still works (backward compat)."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            json={"content": "Hello JSON"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        events = [json.loads(line[6:]) for line in resp.text.split("\n") if line.startswith("data: ")]
        types = [e["type"] for e in events]
        assert "done" in types
