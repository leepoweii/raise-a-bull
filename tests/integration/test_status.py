"""Integration tests for admin status API."""
import pytest
import pytest_asyncio
from unittest.mock import MagicMock
from httpx import AsyncClient, ASGITransport

from raisebull.admin import create_admin_app
from raisebull.admin.credentials_db import init_credentials_db
from raisebull.runner import ClaudeRunner
from raisebull.session import SessionStore


@pytest.fixture
def mock_runner():
    runner = MagicMock(spec=ClaudeRunner)
    runner.model = "MiniMax-M2.7"
    runner.workspace = "/app/workspace"
    return runner


@pytest_asyncio.fixture
async def mock_sessions(tmp_path):
    store = SessionStore(str(tmp_path / "sessions.db"))
    await store.init()
    yield store
    await store.close()


@pytest.fixture
def status_app(tmp_path, monkeypatch, mock_runner, mock_sessions):
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
async def client(status_app):
    from fastapi import FastAPI
    parent = FastAPI()
    parent.mount("/admin", status_app)
    async with AsyncClient(
        transport=ASGITransport(app=parent),
        base_url="http://test",
    ) as c:
        await c.post("/admin/api/auth", json={"password": "testpass123"})
        yield c


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_returns_model_and_workspace(self, client):
        resp = await client.get("/admin/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model"] == "MiniMax-M2.7"
        assert data["workspace"] == "/app/workspace"
        assert data["bot_running"] is False
        assert "bot_username" in data  # str or None
        assert "guilds" in data  # int
        assert "sessions" in data  # dict with total, web, discord, line, heartbeat
        assert isinstance(data["sessions"], dict)
        assert all(k in data["sessions"] for k in ("total", "web", "discord", "line", "heartbeat"))
        assert "heartbeat_last" in data  # None or float

    @pytest.mark.asyncio
    async def test_status_session_counts(self, client, mock_sessions):
        await mock_sessions.save("web:abc", session_id="s1", domain="web", token_count=100)
        await mock_sessions.save("discord:123", session_id="s2", domain="general", token_count=200)
        resp = await client.get("/admin/api/status")
        data = resp.json()
        assert data["sessions"]["total"] == 2
        assert data["sessions"]["web"] == 1
        assert data["sessions"]["discord"] == 1

    @pytest.mark.asyncio
    async def test_heartbeat_last_reflects_live_module_state(self, client, monkeypatch):
        """Regression: heartbeat_last must read the LIVE module variable, not an import-time snapshot.

        Previously routes_status.py did `from raisebull.heartbeat import _last_heartbeat_time`
        which captured None at import time. After heartbeat ticked, the status endpoint still
        returned None. Fixed by importing the module and accessing the variable dynamically.
        """
        import raisebull.heartbeat as hb_mod

        # Reset module state (may be polluted by other tests in the same process)
        original = hb_mod._last_heartbeat_time
        hb_mod._last_heartbeat_time = None

        # Initially None
        resp = await client.get("/admin/api/status")
        assert resp.json()["heartbeat_last"] is None

        # Simulate a heartbeat tick updating the module variable
        hb_mod._last_heartbeat_time = 1234567890.123
        try:
            resp = await client.get("/admin/api/status")
            assert resp.json()["heartbeat_last"] == 1234567890.123

            resp = await client.get("/admin/api/bootstrap")
            assert resp.json()["last_heartbeat_time"] == 1234567890.123
        finally:
            hb_mod._last_heartbeat_time = original

    @pytest.mark.asyncio
    async def test_bootstrap_returns_agent_info(self, client):
        resp = await client.get("/admin/api/bootstrap")
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_name" in data
        assert data["version"] == "0.1.0"
        assert data["bot_connected"] is False
        assert "accent_color" in data
        assert "sessions_count" in data
        assert "last_heartbeat_time" in data
        assert "status" in data
        assert data["status"] == "running"
