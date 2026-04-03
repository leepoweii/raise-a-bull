"""Integration tests for admin dashboard."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from raisebull.admin import create_admin_app
from raisebull.admin.credentials_db import init_credentials_db


@pytest.fixture
def admin_app(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context").mkdir()
    (workspace / "skills").mkdir()
    (workspace / "heartbeat").mkdir()
    (workspace / "config").mkdir()
    db_path = str(tmp_path / "credentials.db")
    init_credentials_db(db_path)
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")
    app = create_admin_app(db_path=db_path, workspace_dir=str(workspace))
    return app


@pytest_asyncio.fixture
async def client(admin_app):
    async with AsyncClient(
        transport=ASGITransport(app=admin_app),
        base_url="http://test",
    ) as c:
        yield c


async def _login(client: AsyncClient) -> AsyncClient:
    resp = await client.post("/api/auth", json={"password": "testpass123"})
    assert resp.status_code == 200
    return client


class TestAuth:
    @pytest.mark.asyncio
    async def test_login_success(self, client):
        resp = await client.post("/api/auth", json={"password": "testpass123"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert "rab_session" in resp.cookies

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        resp = await client.post("/api/auth", json={"password": "wrong"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_without_auth(self, client):
        resp = await client.get("/api/context")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_route_with_auth(self, client):
        await _login(client)
        resp = await client.get("/api/context")
        assert resp.status_code == 200
