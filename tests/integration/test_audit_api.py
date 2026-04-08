"""Integration tests for GET /admin/api/audit endpoint."""
import pytest
import pytest_asyncio
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
    for sub in ["context", "skills", "heartbeat", "config"]:
        (workspace / sub).mkdir()
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


class TestAuditAPI:
    @pytest.mark.asyncio
    async def test_list_audit_requires_auth(self, client):
        resp = await client.get("/admin/api/audit")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_audit_returns_rows_desc(self, client, audit_log):
        await _login(client)
        # Clear login.success row
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        await audit_log.record("login.success", actor="admin")
        await audit_log.record("settings.put", actor="admin", target="model")
        await audit_log.record("session.delete", actor="admin", target="web:abc")

        resp = await client.get("/admin/api/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert "rows" in data
        assert "truncated" in data
        assert data["truncated"] is False
        actions = [r["action"] for r in data["rows"]]
        assert actions == ["session.delete", "settings.put", "login.success"]

    @pytest.mark.asyncio
    async def test_list_audit_date_range_filter(self, client, audit_log):
        await _login(client)
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        # Seed 5 rows at specific timestamps spanning 10 days
        for i, ts in enumerate([
            "2026-04-01T00:00:00+00:00",
            "2026-04-03T00:00:00+00:00",
            "2026-04-05T00:00:00+00:00",
            "2026-04-07T00:00:00+00:00",
            "2026-04-09T00:00:00+00:00",
        ]):
            await db.execute(
                "INSERT INTO audit_log (ts, actor, action) VALUES (?, ?, ?)",
                (ts, "system", f"test.action.{i}"),
            )
        await db.commit()

        resp = await client.get(
            "/admin/api/audit",
            params={
                "from": "2026-04-04T00:00:00+00:00",
                "to": "2026-04-08T00:00:00+00:00",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rows"]) == 2  # 04-05 and 04-07
        ts_list = [r["ts"] for r in data["rows"]]
        assert "2026-04-05T00:00:00+00:00" in ts_list
        assert "2026-04-07T00:00:00+00:00" in ts_list

    @pytest.mark.asyncio
    async def test_list_audit_truncated_flag(self, client, audit_log):
        await _login(client)
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        # Seed 501 rows — use INSERT VALUES for speed
        for i in range(501):
            # Use a unique ts with microsecond offset so ordering is stable
            await db.execute(
                "INSERT INTO audit_log (ts, actor, action) VALUES (?, ?, ?)",
                (f"2026-04-08T00:00:00.{i:06d}+00:00", "system", "scheduler.heartbeat"),
            )
        await db.commit()

        resp = await client.get("/admin/api/audit", params={"limit": "500"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rows"]) == 500
        assert data["truncated"] is True

    @pytest.mark.asyncio
    async def test_list_audit_accepts_z_suffix(self, client, audit_log):
        """Frontend sends Z suffix; backend must normalize to +00:00."""
        await _login(client)
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        # Seed a row stored with +00:00
        await db.execute(
            "INSERT INTO audit_log (ts, actor, action) VALUES (?, ?, ?)",
            ("2026-04-05T12:00:00+00:00", "system", "test.marker"),
        )
        await db.commit()

        # Query with Z suffix (what the dashboard sends)
        resp = await client.get(
            "/admin/api/audit",
            params={
                "from": "2026-04-04T00:00:00Z",
                "to": "2026-04-07T00:00:00Z",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rows"]) == 1
        assert data["rows"][0]["action"] == "test.marker"
