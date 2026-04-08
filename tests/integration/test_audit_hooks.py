"""Integration tests for audit log hook points."""
import pytest
import pytest_asyncio
from pathlib import Path
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from raisebull.admin import create_admin_app
from raisebull.admin.credentials_db import init_credentials_db
from raisebull.audit import AuditLog


@pytest_asyncio.fixture
async def audit_log():
    al = AuditLog(":memory:")
    await al.init()
    yield al
    await al.close()


@pytest.fixture
def admin_app(tmp_path, monkeypatch, audit_log):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context").mkdir()
    (workspace / "skills").mkdir()
    (workspace / "heartbeat").mkdir()
    (workspace / "config").mkdir()
    db_path = str(tmp_path / "credentials.db")
    init_credentials_db(db_path)
    monkeypatch.setenv("ADMIN_PASSWORD", "testpass123")
    app = create_admin_app(
        db_path=db_path,
        workspace_dir=str(workspace),
        audit_log=audit_log,
    )
    return app


@pytest_asyncio.fixture
async def client(admin_app):
    parent = FastAPI()
    parent.mount("/admin", admin_app)
    async with AsyncClient(
        transport=ASGITransport(app=parent),
        base_url="http://test",
    ) as c:
        yield c


async def _login(client: AsyncClient) -> None:
    resp = await client.post("/admin/api/auth", json={"password": "testpass123"})
    assert resp.status_code == 200


class TestLoginHooks:
    @pytest.mark.asyncio
    async def test_login_success_recorded(self, client, audit_log):
        resp = await client.post("/admin/api/auth", json={"password": "testpass123"})
        assert resp.status_code == 200
        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["action"] == "login.success"
        assert rows[0]["actor"] == "admin"
        assert rows[0]["source_ip"] is not None  # ASGITransport gives 127.0.0.1

    @pytest.mark.asyncio
    async def test_login_fail_recorded(self, client, audit_log):
        resp = await client.post("/admin/api/auth", json={"password": "WRONG"})
        assert resp.status_code == 401
        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["action"] == "login.fail"
        assert rows[0]["actor"] == "unknown"

    @pytest.mark.asyncio
    async def test_login_does_not_log_password(self, client, audit_log):
        unique_pw = "HUNT3R2_SECRET_PASSWORD_XYZ"
        await client.post("/admin/api/auth", json={"password": unique_pw})
        rows = await audit_log.list_recent(limit=10)
        # Scan every string field of every row for the password
        for row in rows:
            for value in row.values():
                if isinstance(value, str):
                    assert unique_pw not in value, (
                        f"Password leaked into audit field: {value}"
                    )
