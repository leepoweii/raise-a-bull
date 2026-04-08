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


class TestSessionDeleteHook:
    @pytest.mark.asyncio
    async def test_session_delete_recorded(self, client, audit_log, admin_app):
        await _login(client)
        # Seed an in-memory session via the chat module internals
        from raisebull.admin.routes_chat import _web_sessions
        _web_sessions["web:testdelete"] = {
            "created_at": "2026-04-08T00:00:00+00:00",
            "message_count": 0,
            "name": None,
        }
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        resp = await client.delete("/admin/api/chat/web:testdelete")
        assert resp.status_code == 200
        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["action"] == "session.delete"
        assert rows[0]["actor"] == "admin"
        assert rows[0]["target"] == "web:testdelete"

    @pytest.mark.asyncio
    async def test_session_delete_404_no_audit(self, client, audit_log):
        await _login(client)
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        resp = await client.delete("/admin/api/chat/web:does-not-exist")
        assert resp.status_code == 404
        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 0


class TestInternalHooks:
    """Tests against the full main app (not just the admin sub-app).

    /internal/* routes live on the top-level FastAPI app in main.py and
    use the module-level _audit_log global (not request.app.state).
    """

    @pytest.mark.asyncio
    async def test_internal_heartbeat_trigger_recorded(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        import raisebull.main as main
        from raisebull.audit import AuditLog

        al = AuditLog(":memory:")
        await al.init()
        monkeypatch.setattr(main, "_audit_log", al)
        # Stub out the background work so the test doesn't actually tick
        monkeypatch.setattr(
            main, "run_event_check",
            lambda *a, **kw: _noop_coro(),
        )

        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/internal/heartbeat/trigger")
            assert resp.status_code == 200

        rows = await al.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["action"] == "internal.heartbeat"
        assert rows[0]["actor"] == "system"
        assert rows[0]["source_ip"] is not None
        await al.close()

    @pytest.mark.asyncio
    async def test_internal_nightly_compact_trigger_recorded(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        import raisebull.main as main
        from raisebull.audit import AuditLog

        al = AuditLog(":memory:")
        await al.init()
        monkeypatch.setattr(main, "_audit_log", al)
        monkeypatch.setattr(
            main, "nightly_compact",
            lambda *a, **kw: _noop_coro(),
        )

        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/internal/nightly-compact/trigger")
            assert resp.status_code == 200

        rows = await al.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["action"] == "internal.nightly_compact"
        assert rows[0]["actor"] == "system"
        await al.close()

    @pytest.mark.asyncio
    async def test_internal_discord_push_recorded(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        import raisebull.main as main
        from raisebull.audit import AuditLog

        al = AuditLog(":memory:")
        await al.init()
        monkeypatch.setattr(main, "_audit_log", al)

        # Fake bot + channel to avoid real Discord calls
        class _FakeChannel:
            async def send(self, msg):
                return None

        class _FakeBot:
            def get_channel(self, cid):
                return _FakeChannel()

        monkeypatch.setattr(main, "get_bot", lambda: _FakeBot())

        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post(
                "/internal/discord/push",
                json={"channel_id": "12345", "message": "hello audit"},
            )
            assert resp.status_code == 200

        rows = await al.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["action"] == "internal.discord_push"
        assert rows[0]["actor"] == "system"
        assert rows[0]["target"] == "12345"
        assert rows[0]["after_val"] == "hello audit"
        await al.close()


    @pytest.mark.asyncio
    async def test_internal_localhost_rejection_no_audit(self, monkeypatch, tmp_path):
        """Non-loopback callers get 403 and produce zero audit rows.

        The 403 rejection fires inside _require_localhost BEFORE the
        audit record call, so failed triggers must not leave a trail.
        """
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        import raisebull.main as main
        from raisebull.audit import AuditLog

        al = AuditLog(":memory:")
        await al.init()
        monkeypatch.setattr(main, "_audit_log", al)

        # Wrap main.app in a thin ASGI middleware that rewrites scope["client"]
        # to a non-loopback IP before delegating. This is the standard way to
        # simulate an external caller in ASGITransport-based tests.
        async def _external_ip_app(scope, receive, send):
            if scope["type"] == "http":
                scope = dict(scope)
                scope["client"] = ("203.0.113.5", 54321)
            await main.app(scope, receive, send)

        transport = ASGITransport(app=_external_ip_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.post("/internal/heartbeat/trigger")
            assert resp.status_code == 403

        rows = await al.list_recent(limit=10)
        assert len(rows) == 0
        await al.close()


async def _noop_coro():
    return None


class TestCredentialsHooks:
    """Audit hooks for POST/PUT/DELETE /api/credentials.

    Security invariant: the raw key_value must NEVER appear in any audit
    field. We test this with a unique sentinel string that we grep for
    after each mutation.
    """

    @pytest.mark.asyncio
    async def test_credentials_create_recorded_with_redacted_value(
        self, client, audit_log
    ):
        await _login(client)
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        resp = await client.post(
            "/admin/api/credentials",
            json={
                "key_name": "ANTHROPIC_API_KEY",
                "key_value": "sk-ant-api03-abcdefghijklmnop",
                "service": "anthropic",
            },
        )
        assert resp.status_code == 200

        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "credentials.create"
        assert row["actor"] == "admin"
        assert row["target"] == "ANTHROPIC_API_KEY"
        assert row["before_val"] is None
        assert row["after_val"] == "***mnop"  # last 4 chars only
        assert row["source_ip"] is not None

    @pytest.mark.asyncio
    async def test_credentials_put_key_value_recorded(self, client, audit_log):
        await _login(client)
        # Seed a credential first
        create_resp = await client.post(
            "/admin/api/credentials",
            json={"key_name": "SERPER_API_KEY", "key_value": "old-value-1234", "service": "serper"},
        )
        cred_id = create_resp.json()["id"]

        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        resp = await client.put(
            f"/admin/api/credentials/{cred_id}",
            json={"key_value": "new-value-WXYZ"},
        )
        assert resp.status_code == 200

        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "credentials.put"
        assert row["target"] == "SERPER_API_KEY"  # NOT cred_id — the human-readable name
        assert row["before_val"] is None
        assert row["after_val"] == "***WXYZ"

    @pytest.mark.asyncio
    async def test_credentials_put_service_only_no_value_in_audit(
        self, client, audit_log
    ):
        """Updating only the 'service' field (not key_value) should still
        record the event but with after_val=NULL since no secret changed."""
        await _login(client)
        create_resp = await client.post(
            "/admin/api/credentials",
            json={"key_name": "JINA_API_KEY", "key_value": "unchanged", "service": "old-svc"},
        )
        cred_id = create_resp.json()["id"]
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        resp = await client.put(
            f"/admin/api/credentials/{cred_id}",
            json={"service": "new-svc"},
        )
        assert resp.status_code == 200

        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["action"] == "credentials.put"
        assert rows[0]["target"] == "JINA_API_KEY"
        assert rows[0]["after_val"] is None  # no secret change

    @pytest.mark.asyncio
    async def test_credentials_delete_recorded(self, client, audit_log):
        await _login(client)
        create_resp = await client.post(
            "/admin/api/credentials",
            json={"key_name": "DOOMED_KEY", "key_value": "bye-bye", "service": ""},
        )
        cred_id = create_resp.json()["id"]
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        resp = await client.delete(f"/admin/api/credentials/{cred_id}")
        assert resp.status_code == 200

        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "credentials.delete"
        assert row["target"] == "DOOMED_KEY"
        assert row["before_val"] is None
        assert row["after_val"] is None

    @pytest.mark.asyncio
    async def test_credentials_put_404_no_audit(self, client, audit_log):
        """Updating a nonexistent cred returns 404 and produces zero audit rows."""
        await _login(client)
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        resp = await client.put(
            "/admin/api/credentials/99999",
            json={"key_value": "new"},
        )
        assert resp.status_code == 404
        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_credentials_delete_404_no_audit(self, client, audit_log):
        """Deleting a nonexistent cred returns 404 and produces zero audit rows."""
        await _login(client)
        db = audit_log._require_db()
        await db.execute("DELETE FROM audit_log")
        await db.commit()

        resp = await client.delete("/admin/api/credentials/99999")
        assert resp.status_code == 404
        rows = await audit_log.list_recent(limit=10)
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_credentials_mutations_never_log_full_value(
        self, client, audit_log
    ):
        """Regression guard — scans EVERY audit field for the unique sentinel
        value. If the full value leaks anywhere, this test fails loudly.
        """
        sentinel = "SENTINEL_VALUE_XYZ_MUST_NEVER_APPEAR_IN_AUDIT_abcdef"
        await _login(client)
        # Create
        create_resp = await client.post(
            "/admin/api/credentials",
            json={"key_name": "LEAK_TEST", "key_value": sentinel, "service": "test"},
        )
        cred_id = create_resp.json()["id"]
        # Update to a different full value
        await client.put(
            f"/admin/api/credentials/{cred_id}",
            json={"key_value": sentinel + "_UPDATED"},
        )
        # Delete
        await client.delete(f"/admin/api/credentials/{cred_id}")

        rows = await audit_log.list_recent(limit=10)
        for row in rows:
            for value in row.values():
                if isinstance(value, str):
                    assert sentinel not in value, (
                        f"Credential sentinel leaked into audit field: "
                        f"action={row['action']} field_value={value!r}"
                    )

        # Also verify target field contains the human-readable key_name, not any derived value
        cred_rows = [r for r in rows if r["action"].startswith("credentials.")]
        assert all(row["target"] == "LEAK_TEST" for row in cred_rows), (
            f"Expected target='LEAK_TEST' in all credentials rows, got: {[row['target'] for row in cred_rows]}"
        )
