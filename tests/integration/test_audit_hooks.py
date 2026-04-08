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


class TestSettingsHook:
    @pytest.mark.asyncio
    async def test_settings_put_logs_only_changed_keys(self, client, audit_log):
        await _login(client)
        # Clear the login.success audit row so we only check settings rows
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        # First PUT: establish a known baseline
        await client.put(
            "/admin/api/settings",
            json={"agent_name": "Bull", "max_steps": "100"},
        )
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        # Second PUT: change 2 keys, leave 1 same
        resp = await client.put(
            "/admin/api/settings",
            json={
                "agent_name": "Bull",            # same
                "max_steps": "200",              # changed
                "nightly_compact_threshold": "9999",  # changed (from default 50000)
            },
        )
        assert resp.status_code == 200

        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 2
        targets = {r["target"] for r in rows}
        assert targets == {"max_steps", "nightly_compact_threshold"}
        for row in rows:
            assert row["action"] == "settings.put"
            assert row["actor"] == "admin"
            if row["target"] == "max_steps":
                assert row["before_val"] == "100"
                assert row["after_val"] == "200"

    @pytest.mark.asyncio
    async def test_settings_put_no_change_no_audit(self, client, audit_log):
        await _login(client)
        # Establish baseline
        await client.put(
            "/admin/api/settings",
            json={"agent_name": "Bull"},
        )
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        # PUT same value
        resp = await client.put(
            "/admin/api/settings",
            json={"agent_name": "Bull"},
        )
        assert resp.status_code == 200
        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_settings_put_validation_fail_no_audit(self, client, audit_log):
        await _login(client)
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        # Invalid: nightly_compact_threshold must be positive
        resp = await client.put(
            "/admin/api/settings",
            json={"nightly_compact_threshold": "0"},
        )
        assert resp.status_code == 400
        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 0
