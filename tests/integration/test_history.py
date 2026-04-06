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

    # Create fake .jsonl files simulating Claude Code conversation history
    claude_dir = tmp_path / "claude_home" / ".claude" / "projects" / "-workspace"
    claude_dir.mkdir(parents=True)

    # Normal conversation .jsonl
    jsonl = claude_dir / "test-session-id.jsonl"
    jsonl.write_text("\n".join([
        json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "Hello"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Let me think..."}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi there!"}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/test"}}]}}),
        json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text", "text": "file contents here"}]}]}}),
    ]) + "\n")

    # Corrupted .jsonl
    corrupt = claude_dir / "corrupt-session.jsonl"
    corrupt.write_text("NOT_JSON\n" + json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "valid"}]}}) + "\n{truncated\n")

    # Empty .jsonl
    empty = claude_dir / "empty-session.jsonl"
    empty.write_text("")

    db_path = str(tmp_path / "credentials.db")
    init_credentials_db(db_path)
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")

    store = SessionStore(str(tmp_path / "sessions.db"))
    await store.init()
    await store.save("web:test", session_id="test-session-id", domain="web", token_count=100)
    await store.save("web:corrupt", session_id="corrupt-session", domain="web", token_count=50)
    await store.save("web:empty", session_id="empty-session", domain="web", token_count=0)

    runner = MagicMock(spec=ClaudeRunner)
    runner.workspace = str(workspace)

    app = create_admin_app(
        db_path=db_path, workspace_dir=str(workspace),
        runner=runner, sessions=store,
    )
    # Tell the history endpoint where to find .jsonl files
    app.state.claude_home = str(tmp_path / "claude_home")

    from fastapi import FastAPI
    parent = FastAPI()
    parent.mount("/admin", app)

    async with AsyncClient(
        transport=ASGITransport(app=parent), base_url="http://test",
    ) as client:
        await client.post("/admin/api/auth", json={"password": "testpass123"})
        yield {"client": client, "store": store}

    await store.close()


class TestHistoryAPI:
    @pytest.mark.asyncio
    async def test_returns_parsed_messages(self, setup):
        resp = await setup["client"].get("/admin/api/chat/web:test/history")
        assert resp.status_code == 200
        msgs = resp.json()
        assert isinstance(msgs, list)
        assert len(msgs) >= 3
        # Check user message
        user_msgs = [m for m in msgs if m.get("role") == "user"]
        assert len(user_msgs) >= 1
        assert user_msgs[0]["content"] == "Hello"
        # Check assistant text
        asst_text = [m for m in msgs if m.get("role") == "assistant" and m.get("content")]
        assert any("Hi there" in m["content"] for m in asst_text)
        # Check thinking
        asst_thinking = [m for m in msgs if m.get("role") == "assistant" and m.get("thinking")]
        assert len(asst_thinking) >= 1
        # Check tool_use — arguments must be a JSON string (matches live SSE format)
        asst_tools = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        assert len(asst_tools) >= 1
        tc = asst_tools[0]["tool_calls"][0]
        assert tc["name"] == "Read"
        assert isinstance(tc["arguments"], str)
        assert json.loads(tc["arguments"]) == {"file_path": "/test"}
        # Check tool_result is emitted as role: "tool"
        tool_results = [m for m in msgs if m.get("role") == "tool"]
        assert len(tool_results) >= 1
        assert "file contents" in tool_results[0]["content"]

    @pytest.mark.asyncio
    async def test_missing_session_returns_404(self, setup):
        resp = await setup["client"].get("/admin/api/chat/web:nonexistent/history")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_jsonl_returns_empty(self, setup):
        await setup["store"].save("web:orphan", session_id="no-such-file", domain="web", token_count=0)
        resp = await setup["client"].get("/admin/api/chat/web:orphan/history")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_empty_jsonl_returns_empty(self, setup):
        resp = await setup["client"].get("/admin/api/chat/web:empty/history")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_corrupted_jsonl_skips_bad_lines(self, setup):
        resp = await setup["client"].get("/admin/api/chat/web:corrupt/history")
        assert resp.status_code == 200
        msgs = resp.json()
        # Should have the 1 valid line, skip the 2 bad lines
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "valid"
