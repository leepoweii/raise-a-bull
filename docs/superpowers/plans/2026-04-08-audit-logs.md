# Audit Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured "who did what when" audit trail to raise-a-bull covering dashboard auth, settings mutations, session deletes, LINE signature failures, manual `/internal/*` triggers, APScheduler cron jobs, and heartbeat Discord pushes — with a dashboard viewer page.

**Architecture:** New `AuditLog` class wraps a separate `aiosqlite` connection to the existing `sessions.db`, creating a new `audit_log` table via `CREATE TABLE IF NOT EXISTS` (self-healing migration). 10 hook points call `await audit_log.record(...)` at the appropriate moment. A new `GET /admin/api/audit` endpoint and Alpine.js dashboard page expose the log with server-side date filtering + client-side category filtering.

**Tech Stack:** Python 3.12, aiosqlite, FastAPI, Alpine.js, Playwright, pytest-asyncio, httpx ASGITransport.

**Spec reference:** `docs/superpowers/specs/2026-04-08-audit-logs-design.md`

**Branch:** `feat/audit-logs` (already created from main)

---

## File Map

### New files
- `src/raisebull/audit.py` — `AuditLog` class (aiosqlite, same sessions.db)
- `src/raisebull/admin/routes_audit.py` — `GET /api/audit` router
- `src/raisebull/admin/static/pages/audit.html` — dashboard page markup
- `src/raisebull/admin/static/pages/audit.js` — Alpine.js component
- `tests/unit/test_audit.py` — AuditLog unit tests (6)
- `tests/integration/test_audit_hooks.py` — HTTP hook integration tests (10)
- `tests/integration/test_audit_api.py` — GET endpoint tests (4)
- `tests/integration/test_audit_line.py` — LINE signature hook test (1)
- `tests/test_audit_scheduler.py` — scheduler entry hook tests (3)
- `tests/e2e/audit.spec.ts` — Playwright audit page tests (2)

### Modified files
- `src/raisebull/main.py` — lifespan wiring + `_audit_log` global + 3 `/internal/*` hooks + `webhook_line` signature hook + `heartbeat_push` callback hook
- `src/raisebull/admin/__init__.py` — `audit_log` kwarg on `create_admin_app`, register audit router
- `src/raisebull/admin/auth.py` — login.success / login.fail hooks
- `src/raisebull/admin/routes_settings.py` — settings.put diff + hook
- `src/raisebull/admin/routes_chat.py` — session.delete hook
- `src/raisebull/heartbeat.py` — thread `audit_log` param through `start_heartbeat` / `run_event_check` / `nightly_compact`
- `src/raisebull/admin/static/index.html` — Audit nav entry
- `src/raisebull/admin/static/app.js` — router case for audit page

---

## Task 1: AuditLog class + unit tests

**Files:**
- Create: `src/raisebull/audit.py`
- Create: `tests/unit/test_audit.py`

- [ ] **Step 1: Write the failing unit tests**

Create `tests/unit/test_audit.py`:

```python
"""Unit tests for AuditLog class."""
import pytest
import pytest_asyncio

from raisebull.audit import AuditLog


@pytest_asyncio.fixture
async def audit():
    al = AuditLog(":memory:")
    await al.init()
    yield al
    await al.close()


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_init_creates_table(self, audit):
        # Insert + select with raw SQL proves table + indexes exist
        db = audit._require_db()
        await db.execute(
            "INSERT INTO audit_log (ts, actor, action) VALUES (?, ?, ?)",
            ("2026-04-08T00:00:00+00:00", "admin", "test.action"),
        )
        await db.commit()
        async with db.execute("SELECT COUNT(*) FROM audit_log") as cur:
            row = await cur.fetchone()
            assert row[0] == 1

    @pytest.mark.asyncio
    async def test_record_round_trip(self, audit):
        await audit.record(
            "settings.put",
            actor="admin",
            target="nightly_compact_threshold",
            before_val="50000",
            after_val="9999",
            source_ip="192.168.1.5",
        )
        rows = await audit.list_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["actor"] == "admin"
        assert row["action"] == "settings.put"
        assert row["target"] == "nightly_compact_threshold"
        assert row["before_val"] == "50000"
        assert row["after_val"] == "9999"
        assert row["source_ip"] == "192.168.1.5"
        assert row["ts"].endswith("+00:00")  # UTC isoformat

    @pytest.mark.asyncio
    async def test_record_with_all_nulls(self, audit):
        await audit.record("scheduler.heartbeat", actor="scheduler")
        rows = await audit.list_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["target"] is None
        assert row["before_val"] is None
        assert row["after_val"] is None
        assert row["source_ip"] is None

    @pytest.mark.asyncio
    async def test_list_recent_ordered_desc(self, audit):
        await audit.record("login.success", actor="admin")
        await audit.record("settings.put", actor="admin", target="model")
        await audit.record("session.delete", actor="admin", target="web:abc")
        rows = await audit.list_recent(limit=10)
        assert [r["action"] for r in rows] == [
            "session.delete", "settings.put", "login.success"
        ]

    @pytest.mark.asyncio
    async def test_list_recent_date_range_filter(self, audit):
        # Insert rows at specific timestamps using raw SQL
        db = audit._require_db()
        for ts in [
            "2026-04-01T00:00:00+00:00",
            "2026-04-05T12:00:00+00:00",
            "2026-04-10T23:59:59+00:00",
        ]:
            await db.execute(
                "INSERT INTO audit_log (ts, actor, action) VALUES (?, ?, ?)",
                (ts, "system", "scheduler.heartbeat"),
            )
        await db.commit()

        rows = await audit.list_recent(
            from_ts="2026-04-04T00:00:00+00:00",
            to_ts="2026-04-07T00:00:00+00:00",
            limit=10,
        )
        assert len(rows) == 1
        assert rows[0]["ts"] == "2026-04-05T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_list_recent_limit(self, audit):
        for i in range(10):
            await audit.record("scheduler.heartbeat", actor="scheduler")
        rows = await audit.list_recent(limit=5)
        assert len(rows) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
uv run pytest tests/unit/test_audit.py -v
```

Expected: `ImportError: cannot import name 'AuditLog' from 'raisebull.audit'` or `ModuleNotFoundError: No module named 'raisebull.audit'`

- [ ] **Step 3: Write AuditLog implementation**

Create `src/raisebull/audit.py`:

```python
"""Append-only audit log backed by SQLite.

Lifecycle mirrors SessionStore: construct with db_path, await init() to
open connection + create table, await close() to release connection.
The audit_log table lives in the same sessions.db file as SessionStore
and MessageBuffer — each class holds its own aiosqlite connection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import aiosqlite


class AuditLog:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
        """Open the connection and create the audit_log table + indexes."""
        self._db = await aiosqlite.connect(self._db_path, timeout=10)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                actor       TEXT NOT NULL,
                action      TEXT NOT NULL,
                target      TEXT,
                before_val  TEXT,
                after_val   TEXT,
                source_ip   TEXT
            )
            """
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_ts ON audit_log(ts DESC)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action)"
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _require_db(self) -> "aiosqlite.Connection":
        if self._db is None:
            raise RuntimeError("AuditLog.init() has not been awaited")
        return self._db

    async def record(
        self,
        action: str,
        *,
        actor: str = "system",
        target: Optional[str] = None,
        before_val: Optional[str] = None,
        after_val: Optional[str] = None,
        source_ip: Optional[str] = None,
    ) -> None:
        """Append one audit row. Timestamp is generated now (UTC ISO 8601)."""
        ts = datetime.now(timezone.utc).isoformat()
        await self._require_db().execute(
            """
            INSERT INTO audit_log
                (ts, actor, action, target, before_val, after_val, source_ip)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, actor, action, target, before_val, after_val, source_ip),
        )
        await self._require_db().commit()

    async def list_recent(
        self,
        *,
        from_ts: Optional[str] = None,
        to_ts: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return rows matching the date range, newest first.

        from_ts / to_ts are ISO 8601 strings. Pass `limit + 1` from the
        caller to detect truncation.
        """
        async with self._require_db().execute(
            """
            SELECT id, ts, actor, action, target, before_val, after_val, source_ip
            FROM audit_log
            WHERE (? IS NULL OR ts >= ?)
              AND (? IS NULL OR ts <= ?)
            ORDER BY ts DESC
            LIMIT ?
            """,
            (from_ts, from_ts, to_ts, to_ts, limit),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_audit.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/audit.py tests/unit/test_audit.py
git commit -m "feat(audit): add AuditLog class with SQLite backend

New AuditLog class mirrors SessionStore / MessageBuffer lifecycle:
construct → init() → record() / list_recent() → close(). Creates
audit_log table + ts DESC / action indexes via CREATE TABLE IF NOT
EXISTS for self-healing migration.

6 unit tests in tests/unit/test_audit.py covering init, round-trip,
NULL columns, ordering, date range filter, and limit.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Wire AuditLog into lifespan + admin state

**Files:**
- Modify: `src/raisebull/main.py` (lifespan + module global)
- Modify: `src/raisebull/admin/__init__.py` (accept audit_log kwarg)

No tests in this task — wiring is exercised by the integration tests in later tasks.

- [ ] **Step 1: Add `audit_log` kwarg to `create_admin_app`**

In `src/raisebull/admin/__init__.py`, modify the signature and state assignment:

```python
def create_admin_app(
    db_path: str | None = None,
    workspace_dir: str | None = None,
    bot_fn=None,
    runner=None,
    sessions=None,
    audit_log=None,
) -> FastAPI:
    app = FastAPI(title="raise-a-bull Admin")

    data_dir = os.getenv("DATA_DIR", "/app/data")
    app.state.db_path = db_path or os.path.join(data_dir, "credentials.db")
    app.state.workspace_dir = workspace_dir or os.getenv("WORKSPACE", "/app/workspace")
    app.state.bot_fn = bot_fn
    app.state.runner = runner
    app.state.sessions = sessions
    app.state.audit_log = audit_log

    init_credentials_db(app.state.db_path)
    ...
```

- [ ] **Step 2: Add module-level `_audit_log` global + lifespan wiring in main.py**

In `src/raisebull/main.py` (near the existing `_sessions` / `_runner` globals at line ~124):

```python
from raisebull.audit import AuditLog

_sessions: SessionStore | None = None
_runner: ClaudeRunner | None = None
_message_buffer: MessageBuffer | None = None
_heartbeat_push = None
_audit_log: AuditLog | None = None
```

In the `lifespan` function, after `_sessions.init()` (around line 144), add:

```python
    _sessions = SessionStore(db_path=os.getenv("DB_PATH", "/app/data/sessions.db"))
    await _sessions.init()

    _audit_log = AuditLog(db_path=os.getenv("DB_PATH", "/app/data/sessions.db"))
    await _audit_log.init()
```

After `_admin_app.state.sessions = _sessions` (around line 157), add:

```python
    _admin_app.state.runner = _runner
    _admin_app.state.sessions = _sessions
    _admin_app.state.audit_log = _audit_log
```

In the shutdown block (end of lifespan, around line 192), add:

```python
    if _audit_log is not None:
        await _audit_log.close()
    if _sessions is not None:
        await _sessions.close()
```

Also update the `global` declaration at the top of lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sessions, _runner, _message_buffer, _heartbeat_push, _audit_log
```

- [ ] **Step 3: Run the existing admin tests to confirm nothing broke**

```bash
uv run pytest tests/integration/test_admin.py -v
```

Expected: all existing admin tests still pass (audit_log defaults to None, no behavior change).

- [ ] **Step 4: Commit**

```bash
git add src/raisebull/main.py src/raisebull/admin/__init__.py
git commit -m "feat(audit): wire AuditLog into lifespan + admin sub-app state

Opens a second aiosqlite connection to the same sessions.db for the
audit_log table. _audit_log module-level global is used directly by
main.py /internal/* routes (mirrors the existing _sessions pattern);
admin sub-app routes access it via request.app.state.audit_log.

create_admin_app() gains an audit_log kwarg (defaults to None) so
tests can inject a :memory: instance.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: login hooks (auth.py)

**Files:**
- Modify: `src/raisebull/admin/auth.py:56-64` (login_endpoint)
- Create: `tests/integration/test_audit_hooks.py` (initial shell + 3 tests)

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_audit_hooks.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestLoginHooks -v
```

Expected: 3 failures — no audit rows are recorded because `login_endpoint` doesn't call `audit_log.record()` yet.

- [ ] **Step 3: Add hooks to `login_endpoint`**

Replace the body of `login_endpoint` in `src/raisebull/admin/auth.py`:

```python
async def login_endpoint(request: Request):
    body = await request.json()
    password = body.get("password", "")
    expected = _get_password()
    audit_log = getattr(request.app.state, "audit_log", None)
    source_ip = request.client.host if request.client else None

    if not expected or not hmac.compare_digest(password, expected):
        if audit_log is not None:
            await audit_log.record(
                "login.fail", actor="unknown", source_ip=source_ip
            )
        return JSONResponse({"error": "Invalid password"}, status_code=401)

    if audit_log is not None:
        await audit_log.record(
            "login.success", actor="admin", source_ip=source_ip
        )
    response = JSONResponse({"ok": True})
    create_session_cookie(response)
    return response
```

**Security note:** `body` dict is NEVER passed to `record()`. Only the success/fail boolean + IP are recorded.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestLoginHooks -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/admin/auth.py tests/integration/test_audit_hooks.py
git commit -m "feat(audit): hook login.success / login.fail in auth.py

Records login attempts (success + fail) with source_ip. Password
payload is NEVER passed to record() — only the boolean outcome is
logged. Tests verify password does not leak into any audit field.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: settings.put hook

**Files:**
- Modify: `src/raisebull/admin/routes_settings.py:109-135` (put_settings)
- Modify: `tests/integration/test_audit_hooks.py` (add TestSettingsHook class)

- [ ] **Step 1: Add failing tests to test_audit_hooks.py**

Append to `tests/integration/test_audit_hooks.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestSettingsHook -v
```

Expected: 3 failures — `put_settings` doesn't call `audit_log.record()` yet.

- [ ] **Step 3: Modify `put_settings` to diff and record**

Replace the body of `put_settings` in `src/raisebull/admin/routes_settings.py` (lines 109-135):

```python
@router.put("")
async def put_settings(request: Request):
    body = await request.json()

    # Validate every numeric setting present in the body. The first invalid key
    # wins (deterministic order via _NUMERIC_CONSTRAINTS dict iteration).
    for key in _NUMERIC_CONSTRAINTS:
        if key in body:
            err = _validate_numeric_setting(key, body[key])
            if err:
                return JSONResponse({"error": err}, status_code=400)

    audit_log = getattr(request.app.state, "audit_log", None)
    source_ip = request.client.host if request.client else None

    path = _settings_path(request)
    current = _read_settings(path)
    changes: list[tuple[str, str, str]] = []  # (key, before, after)
    for key in _ALLOWED_KEYS:
        if key in body:
            new_val = str(body[key])
            old_val = current[key]
            if new_val != old_val:
                changes.append((key, old_val, new_val))
            current[key] = new_val

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))

    if audit_log is not None and changes:
        for key, before, after in changes:
            await audit_log.record(
                "settings.put",
                actor="admin",
                target=key,
                before_val=before,
                after_val=after,
                source_ip=source_ip,
            )
    return {"ok": True}
```

Note: record calls are AFTER `os.replace()` succeeds — if file write fails, no phantom audit rows.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestSettingsHook -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/admin/routes_settings.py tests/integration/test_audit_hooks.py
git commit -m "feat(audit): hook settings.put with per-key diff

PUT /admin/api/settings now records one audit row per actually-changed
key. No-op PUTs (body value matches current) and 400 validation
failures produce zero audit rows. Record calls happen AFTER os.replace
succeeds to avoid phantom rows on file write failure.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: session.delete hook

**Files:**
- Modify: `src/raisebull/admin/routes_chat.py:107-137` (delete_session)
- Modify: `tests/integration/test_audit_hooks.py` (add TestSessionDeleteHook class)

- [ ] **Step 1: Add failing tests to test_audit_hooks.py**

Append to `tests/integration/test_audit_hooks.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestSessionDeleteHook -v
```

Expected: 1 failure (`test_session_delete_recorded` — no audit row written) and 1 pass (`test_session_delete_404_no_audit` — trivially 0 rows, but keep it for regression coverage).

- [ ] **Step 3: Add hook to `delete_session`**

In `src/raisebull/admin/routes_chat.py`, modify `delete_session` to add the audit call right before the final return. The updated function:

```python
@router.delete("/api/chat/{session_id}")
async def delete_session(session_id: str, request: Request):
    sessions_store = getattr(request.app.state, "sessions", None)

    # Check if session exists (in-memory or DB)
    in_memory = session_id in _web_sessions
    in_db = False
    if sessions_store:
        row = await sessions_store.get(session_id)
        in_db = row is not None

    if not in_memory and not in_db:
        return JSONResponse({"error": "session not found"}, status_code=404)

    _web_sessions.pop(session_id, None)

    if sessions_store:
        await sessions_store.clear(session_id)

    import os
    import shutil
    workspace = getattr(getattr(request.app.state, "runner", None), "workspace", None)
    if workspace:
        uploads_dir = os.path.join(workspace, "uploads", session_id)
        if os.path.isdir(uploads_dir):
            shutil.rmtree(uploads_dir, ignore_errors=True)

    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is not None:
        await audit_log.record(
            "session.delete",
            actor="admin",
            target=session_id,
            source_ip=request.client.host if request.client else None,
        )

    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestSessionDeleteHook -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/admin/routes_chat.py tests/integration/test_audit_hooks.py
git commit -m "feat(audit): hook session.delete in routes_chat.py

DELETE /admin/api/chat/{id} records target=session_id + source_ip.
404 (session not found) returns early before the audit call, so
failed deletes produce zero audit rows.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: /internal/* hooks (3 routes in main.py)

**Files:**
- Modify: `src/raisebull/main.py` (`/internal/heartbeat/trigger`, `/internal/nightly-compact/trigger`, `/internal/discord/push`)
- Modify: `tests/integration/test_audit_hooks.py` (add TestInternalHooks)

- [ ] **Step 1: Add failing tests**

Append to `tests/integration/test_audit_hooks.py`:

```python
class TestInternalHooks:
    """Tests against the full main app (not just the admin sub-app).

    /internal/* routes live on the top-level FastAPI app in main.py and
    use the module-level _audit_log global (not request.app.state).
    """

    @pytest.mark.asyncio
    async def test_internal_heartbeat_trigger_recorded(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")

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
    async def test_internal_nightly_compact_trigger_recorded(self, monkeypatch):
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")

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
    async def test_internal_discord_push_recorded(self, monkeypatch):
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")

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
    async def test_internal_localhost_rejection_no_audit(self, monkeypatch):
        """Non-loopback callers get 403 and produce zero audit rows.

        The 403 rejection fires inside _require_localhost BEFORE the
        audit record call, so failed triggers must not leave a trail.
        """
        monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
        monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestInternalHooks -v
```

Expected: 3 failures — `/internal/*` routes don't call `_audit_log.record()` yet.

- [ ] **Step 3: Add hooks to `/internal/*` routes in main.py**

In `src/raisebull/main.py`, update the three `/internal/*` handlers:

```python
@app.post("/internal/discord/push")
async def discord_push(req: DiscordPushRequest, request: Request) -> dict[str, Any]:
    """Push a message to a Discord channel via the running bot. Localhost only."""
    _require_localhost(request)
    if _audit_log is not None:
        await _audit_log.record(
            "internal.discord_push",
            actor="system",
            target=req.channel_id,
            after_val=req.message[:200],
            source_ip=request.client.host if request.client else None,
        )
    bot = get_bot()
    if bot is None:
        raise HTTPException(status_code=503, detail="Discord bot not running")
    channel = bot.get_channel(int(req.channel_id))
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel {req.channel_id} not in cache")
    await channel.send(req.message)
    return {"ok": True, "channel_id": req.channel_id}


@app.post("/internal/heartbeat/trigger")
async def heartbeat_trigger(request: Request) -> dict[str, Any]:
    """Manually trigger one heartbeat tick (for testing). Localhost only."""
    _require_localhost(request)
    if _audit_log is not None:
        await _audit_log.record(
            "internal.heartbeat",
            actor="system",
            source_ip=request.client.host if request.client else None,
        )
    asyncio.create_task(run_event_check(_runner, _sessions, push_fn=_heartbeat_push))
    return {"ok": True, "message": "heartbeat tick started"}


@app.post("/internal/nightly-compact/trigger")
async def nightly_compact_trigger(request: Request) -> dict[str, Any]:
    """Manually trigger nightly compact (for testing). Localhost only."""
    _require_localhost(request)
    if _audit_log is not None:
        await _audit_log.record(
            "internal.nightly_compact",
            actor="system",
            source_ip=request.client.host if request.client else None,
        )
    asyncio.create_task(nightly_compact(_runner, _sessions, buffer=_message_buffer))
    return {"ok": True, "message": "nightly compact started"}
```

**Order invariant:** record is called AFTER `_require_localhost()` (so 403 rejections don't produce audit rows) but BEFORE the background task / bot call (so even if that fails, the audit trail shows someone tried).

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestInternalHooks -v
```

Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/main.py tests/integration/test_audit_hooks.py
git commit -m "feat(audit): hook 3 /internal/* manual trigger routes

Records internal.heartbeat, internal.nightly_compact, and
internal.discord_push with actor=system + source_ip (always loopback
since these routes pass _require_localhost first). discord_push
additionally records target=channel_id and after_val=message[:200]
so the audit log shows what content was manually pushed.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: LINE signature_fail hook

**Files:**
- Modify: `src/raisebull/main.py:282-320` (webhook_line)
- Create: `tests/integration/test_audit_line.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_audit_line.py`:

```python
"""Audit log coverage for LINE webhook signature failures."""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_line_signature_fail_recorded(monkeypatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "test-secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "test-token")

    import raisebull.main as main
    from raisebull.audit import AuditLog

    al = AuditLog(":memory:")
    await al.init()
    monkeypatch.setattr(main, "_audit_log", al)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Invalid signature — webhook parser will reject
        resp = await c.post(
            "/webhook/line",
            content=b'{"events": []}',
            headers={
                "X-Line-Signature": "invalid-signature-xyz",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 400

    rows = await al.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "line.signature_fail"
    assert rows[0]["actor"] == "unknown"
    await al.close()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/integration/test_audit_line.py -v
```

Expected: 1 failure — no audit row on signature failure.

- [ ] **Step 3: Add hook to webhook_line**

In `src/raisebull/main.py`, modify the `webhook_line` function:

```python
@app.post("/webhook/line")
async def webhook_line(request: Request) -> Response:
    """Receive LINE webhook events."""
    channel_secret = os.getenv("LINE_CHANNEL_SECRET", "")
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

    body = await request.body()
    body_text = body.decode("utf-8")

    signature = request.headers.get("X-Line-Signature", "")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature header")

    parser = WebhookParser(channel_secret)
    try:
        events = parser.parse(body_text, signature)
    except InvalidSignatureError:
        if _audit_log is not None:
            await _audit_log.record(
                "line.signature_fail",
                actor="unknown",
                source_ip=request.client.host if request.client else None,
            )
        raise HTTPException(status_code=400, detail="Invalid signature")

    # ... rest of function unchanged ...
```

Leave the rest of the function body (the `_process` inner function and the `asyncio.create_task` call) exactly as-is.

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/integration/test_audit_line.py -v
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/main.py tests/integration/test_audit_line.py
git commit -m "feat(audit): hook line.signature_fail on LINE webhook

Records invalid LINE webhook signatures as a security event (parallel
to login.fail). actor=unknown + source_ip lets forensics correlate
spoof attempts to specific external IPs.

Does NOT log the body text or any LINE event content — only the
boolean failure + IP.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: heartbeat.py scheduler hooks (parameter threading)

**Files:**
- Modify: `src/raisebull/heartbeat.py` (`start_heartbeat`, `run_event_check`, `nightly_compact` — accept audit_log kwarg)
- Modify: `src/raisebull/main.py` lifespan (pass `_audit_log` into `start_heartbeat`)
- Modify: `src/raisebull/main.py` `/internal/*` triggers (pass `_audit_log` through `run_event_check`/`nightly_compact` calls)
- Create: `tests/test_audit_scheduler.py` (2 tests — `scheduler.heartbeat` + `scheduler.nightly_compact`)

- [ ] **Step 1: Write failing tests**

Create `tests/test_audit_scheduler.py`:

```python
"""Audit log coverage for scheduler entry points in heartbeat.py."""
import pytest

from raisebull.audit import AuditLog


@pytest.mark.asyncio
async def test_scheduler_heartbeat_recorded(monkeypatch, tmp_path):
    from raisebull.heartbeat import run_event_check

    al = AuditLog(":memory:")
    await al.init()

    # Stub out the actual work: runner.run and sessions access
    class _FakeRunner:
        workspace = str(tmp_path)

        async def run(self, *args, **kwargs):
            class _Result:
                session_id = None
                output = ""
                input_tokens = 0
                output_tokens = 0
                error = None
                stale_session = False
            return _Result()

    class _FakeSessions:
        async def get(self, key):
            return None

        async def save(self, *args, **kwargs):
            return None

    # Create an empty heartbeat.md so the function has nothing to do
    (tmp_path / "heartbeat").mkdir(exist_ok=True)
    (tmp_path / "heartbeat" / "heartbeat.md").write_text("# Empty\n")
    monkeypatch.setenv("WORKSPACE", str(tmp_path))

    # The audit call is at the top of _heartbeat_tick (before any file I/O
    # or runner logic). Wrap in try/except so the test only asserts the
    # audit row was written, even if downstream _heartbeat_tick logic
    # raises on the stub fixtures.
    try:
        await run_event_check(
            _FakeRunner(),
            _FakeSessions(),
            push_fn=None,
            audit_log=al,
        )
    except Exception:
        pass

    rows = await al.list_recent(limit=10)
    assert len(rows) >= 1
    assert any(
        r["action"] == "scheduler.heartbeat" and r["actor"] == "scheduler"
        for r in rows
    )
    await al.close()


@pytest.mark.asyncio
async def test_scheduler_nightly_compact_recorded(monkeypatch, tmp_path):
    from raisebull.heartbeat import nightly_compact

    al = AuditLog(":memory:")
    await al.init()

    class _FakeRunner:
        workspace = str(tmp_path)

        async def run(self, *args, **kwargs):
            class _Result:
                session_id = None
                output = ""
                input_tokens = 0
                output_tokens = 0
                error = None
                stale_session = False
            return _Result()

    class _FakeSessions:
        async def list_all(self):
            return []  # no eligible sessions

        async def get(self, key):
            return None

    try:
        await nightly_compact(
            _FakeRunner(),
            _FakeSessions(),
            buffer=None,
            audit_log=al,
        )
    except Exception:
        pass

    rows = await al.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "scheduler.nightly_compact"
    assert rows[0]["actor"] == "scheduler"
    await al.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_audit_scheduler.py -v
```

Expected: 2 failures — `run_event_check` / `nightly_compact` don't accept `audit_log` kwarg.

- [ ] **Step 3: Thread `audit_log` through heartbeat.py**

**IMPORTANT:** APScheduler in `start_heartbeat` registers `_heartbeat_tick` directly (line 262, NOT `run_event_check`) and `nightly_compact` directly (line 269) with **positional `args=[...]` lists** — not closures or kwargs. `run_event_check` (line 282) is a thin wrapper that only gets called from `/internal/heartbeat/trigger`, not from APScheduler. To capture the cron path, the `scheduler.heartbeat` audit call must live in `_heartbeat_tick`, not `run_event_check`.

Edit `src/raisebull/heartbeat.py`:

1. Add import at top (after the existing `from raisebull.session import SessionStore`):
```python
from raisebull.audit import AuditLog
```

2. Update `_heartbeat_tick` signature (line 126) — add `audit_log` kwarg and record at entry:

```python
async def _heartbeat_tick(
    runner: ClaudeRunner,
    sessions: SessionStore,
    push_fn=None,
    audit_log: AuditLog | None = None,
) -> None:
    if audit_log is not None:
        await audit_log.record("scheduler.heartbeat", actor="scheduler")
    global _last_heartbeat_response, _last_heartbeat_time
    now = datetime.now()
    # ... rest of existing body unchanged ...
```

3. Update `run_event_check` signature (line 282) to forward `audit_log` into `_heartbeat_tick`:

```python
async def run_event_check(
    runner: ClaudeRunner,
    sessions: SessionStore,
    push_fn=None,
    audit_log: AuditLog | None = None,
) -> None:
    await _heartbeat_tick(runner, sessions, push_fn=push_fn, audit_log=audit_log)
```

(Note: `run_event_check` no longer records directly — it delegates to `_heartbeat_tick` so both the `/internal/heartbeat/trigger` path and the APScheduler path produce identical audit rows via a single hook location.)

4. Update `nightly_compact` signature (line 173) — add `audit_log` kwarg and record at entry:

```python
async def nightly_compact(
    runner: ClaudeRunner,
    sessions: SessionStore,
    buffer=None,
    audit_log: AuditLog | None = None,
) -> None:
    """..."""  # keep existing docstring
    async with _nightly_lock:
        if audit_log is not None:
            await audit_log.record("scheduler.nightly_compact", actor="scheduler")
        # ... rest of existing body unchanged ...
```

5. Update `start_heartbeat` signature (line 254) — accept `audit_log` and pass it via the APScheduler `args=[...]` positional lists:

```python
def start_heartbeat(
    runner: ClaudeRunner,
    sessions: SessionStore,
    push_fn=None,
    buffer=None,
    audit_log: AuditLog | None = None,
) -> None:
    global _scheduler
    if HEARTBEAT_INTERVAL <= 0:
        logger.info("Heartbeat disabled (interval <= 0)")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _heartbeat_tick, "interval", seconds=HEARTBEAT_INTERVAL,
        args=[runner, sessions, push_fn, audit_log], max_instances=1,
    )

    # Nightly compact job
    compact_hour = int(os.environ.get("NIGHTLY_COMPACT_HOUR", "3"))
    _scheduler.add_job(
        nightly_compact,
        "cron",
        hour=compact_hour,
        minute=0,
        args=[runner, sessions, buffer, audit_log],
        id="nightly_compact",
    )
    logger.info("Nightly compact scheduled at %02d:00", compact_hour)

    _scheduler.start()
    logger.info("Heartbeat started: interval=%ds", HEARTBEAT_INTERVAL)
```

**Why positional `args=[...]` lists must be extended:** APScheduler passes `args` as positional arguments to the target function. Since `_heartbeat_tick` and `nightly_compact` now accept `audit_log` as the 4th positional (or kwarg after push_fn/buffer), appending `audit_log` to the args list threads it through. Leaving the original 3-element args list would call the function with `audit_log` defaulting to `None`, producing zero `scheduler.*` rows on the cron path — and the unit tests in Step 1 would still pass because they call the functions directly.

- [ ] **Step 4: Update main.py lifespan to pass `_audit_log` into `start_heartbeat`**

In `src/raisebull/main.py` lifespan, modify the `start_heartbeat` call:

```python
    start_heartbeat(
        _runner, _sessions,
        push_fn=_heartbeat_push,
        buffer=_message_buffer,
        audit_log=_audit_log,
    )
```

Also update the `/internal/heartbeat/trigger` and `/internal/nightly-compact/trigger` handlers in main.py to pass `_audit_log`:

```python
    asyncio.create_task(run_event_check(
        _runner, _sessions, push_fn=_heartbeat_push, audit_log=_audit_log
    ))
```

```python
    asyncio.create_task(nightly_compact(
        _runner, _sessions, buffer=_message_buffer, audit_log=_audit_log
    ))
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_audit_scheduler.py -v
```

Expected: 2 passed

- [ ] **Step 6: Run existing heartbeat tests to confirm no regressions**

```bash
uv run pytest tests/unit/test_heartbeat_parse.py tests/unit/test_nightly_compact.py -v
```

Expected: all existing tests still pass (the new kwarg has a default of None).

- [ ] **Step 7: Commit**

```bash
git add src/raisebull/heartbeat.py src/raisebull/main.py tests/test_audit_scheduler.py
git commit -m "feat(audit): hook scheduler.heartbeat + scheduler.nightly_compact

Threads optional audit_log parameter through start_heartbeat,
run_event_check, and nightly_compact. APScheduler cron entries now
record scheduler.heartbeat (per tick) and scheduler.nightly_compact
(per nightly run) so forensics can distinguish 'cron actually ran'
from 'someone manually triggered via /internal/*'.

Backwards compatible: the new kwarg defaults to None and the hook
is guarded by if audit_log is not None.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9: heartbeat_push → scheduler.discord_push hook

**Files:**
- Modify: `src/raisebull/main.py` (`heartbeat_push` inner function in lifespan)
- Modify: `tests/test_audit_scheduler.py` (add third test)

- [ ] **Step 1: Add failing test**

Append to `tests/test_audit_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_scheduler_discord_push_records_truncated_message(monkeypatch):
    """The heartbeat_push callback records only the first 200 chars of content."""
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")

    import raisebull.main as main

    al = AuditLog(":memory:")
    await al.init()
    monkeypatch.setattr(main, "_audit_log", al)

    # Build a fake bot with one guild + one text_channel
    class _FakeChannel:
        name = "daily-ops"
        sent: list[str] = []

        async def send(self, msg):
            self.sent.append(msg)

    class _FakeGuild:
        text_channels = [_FakeChannel()]

    class _FakeBot:
        guilds = [_FakeGuild()]

    monkeypatch.setattr(main, "get_bot", lambda: _FakeBot())

    # Re-create the push callback with the stubbed _audit_log visible
    # (the real one is closured in lifespan — we need to call it here)
    # For testability, the implementation uses the module-level _audit_log
    # so we can call it directly.
    import discord  # noqa: F401 — matches production import path

    long_message = "X" * 500

    # Call the push callback function directly. The implementation
    # is defined in main.py lifespan; we access it via main._heartbeat_push
    # after a minimal lifespan setup. Simpler: instantiate a standalone
    # function mirroring the one in lifespan, but since this test targets
    # the real callback, we call main.lifespan's internal helper by
    # extracting it via monkeypatch. For now, call the module-level
    # helper `_heartbeat_push_impl` we will add in Step 3.
    from raisebull.main import _heartbeat_push_impl
    await _heartbeat_push_impl("daily-ops", long_message)

    rows = await al.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "scheduler.discord_push"
    assert rows[0]["actor"] == "scheduler"
    assert rows[0]["target"] == "daily-ops"
    assert rows[0]["after_val"] == "X" * 200  # truncated to 200 chars
    await al.close()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_audit_scheduler.py::test_scheduler_discord_push_records_truncated_message -v
```

Expected: `ImportError: cannot import name '_heartbeat_push_impl'`

- [ ] **Step 3: Refactor `heartbeat_push` into a module-level helper + add hook**

In `src/raisebull/main.py`, extract the existing inner `heartbeat_push` function from lifespan into a module-level function, and add the audit hook after a successful send:

```python
# Near the other module-level helpers (after _require_localhost), add:

async def _heartbeat_push_impl(channel_name: str, message: str) -> None:
    """Push a heartbeat-triggered message to a Discord text channel.

    Records a scheduler.discord_push audit event on successful send.
    Extracted from lifespan for direct testability.
    """
    bot_instance = get_bot()
    if bot_instance is None:
        logger.warning("Heartbeat push: bot not running, skipping #%s", channel_name)
        return
    guild = bot_instance.guilds[0] if bot_instance.guilds else None
    if guild is None:
        return
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    if channel:
        await channel.send(message[:2000])
        if _audit_log is not None:
            await _audit_log.record(
                "scheduler.discord_push",
                actor="scheduler",
                target=channel_name,
                after_val=message[:200],
            )
    else:
        logger.warning("Heartbeat push: #%s not found", channel_name)
```

In the `lifespan` function, replace the inline `heartbeat_push` closure with a reference to `_heartbeat_push_impl`:

```python
    _heartbeat_push = _heartbeat_push_impl
    start_heartbeat(
        _runner, _sessions,
        push_fn=_heartbeat_push,
        buffer=_message_buffer,
        audit_log=_audit_log,
    )
```

Delete the old inner `async def heartbeat_push(...)` function since its body is now in `_heartbeat_push_impl`.

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_audit_scheduler.py::test_scheduler_discord_push_records_truncated_message -v
```

Expected: 1 passed

- [ ] **Step 5: Run all audit scheduler tests together**

```bash
uv run pytest tests/test_audit_scheduler.py -v
```

Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
git add src/raisebull/main.py tests/test_audit_scheduler.py
git commit -m "feat(audit): hook scheduler.discord_push with truncated message

Extracts heartbeat_push from lifespan closure into _heartbeat_push_impl
at module level so tests can call it directly. After successful
channel.send, records target=channel_name + after_val=message[:200].

The 200-char truncation is the whole point of this audit row —
forensics wants to see 'what got pushed to #daily-ops at 03:42' without
bloating the DB with full heartbeat outputs.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 10: GET /admin/api/audit endpoint

**Files:**
- Create: `src/raisebull/admin/routes_audit.py`
- Modify: `src/raisebull/admin/__init__.py` (register router)
- Create: `tests/integration/test_audit_api.py` (4 tests)

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_audit_api.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_audit_api.py -v
```

Expected: 4 failures — route `/admin/api/audit` returns 404 (not registered).

- [ ] **Step 3: Create routes_audit.py**

Create `src/raisebull/admin/routes_audit.py`:

```python
"""Read API for audit_log — GET /admin/api/audit with date + limit filter."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/audit")

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 2000


@router.get("")
async def list_audit(request: Request):
    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is None:
        return JSONResponse(
            {"error": "audit log not initialized"}, status_code=503
        )

    qp = request.query_params
    from_ts = qp.get("from")
    to_ts = qp.get("to")

    try:
        limit = int(qp.get("limit", _DEFAULT_LIMIT))
    except ValueError:
        return JSONResponse(
            {"error": "limit must be an integer"}, status_code=400
        )
    if limit < 1 or limit > _MAX_LIMIT:
        return JSONResponse(
            {"error": f"limit must be between 1 and {_MAX_LIMIT}"},
            status_code=400,
        )

    # Fetch limit + 1 to detect truncation without a separate COUNT query
    rows = await audit_log.list_recent(
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit + 1,
    )
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    return {
        "rows": rows,
        "truncated": truncated,
        "limit": limit,
        "from": from_ts,
        "to": to_ts,
    }
```

- [ ] **Step 4: Register router in admin/__init__.py**

In `src/raisebull/admin/__init__.py`, add the import and `include_router` alongside the existing 9 routers:

```python
    from raisebull.admin.routes_status import router as status_router
    from raisebull.admin.routes_context import router as context_router
    from raisebull.admin.routes_skills import router as skills_router
    from raisebull.admin.routes_heartbeat import router as heartbeat_router
    from raisebull.admin.routes_credentials import router as credentials_router
    from raisebull.admin.routes_settings import router as settings_router
    from raisebull.admin.routes_permissions import router as permissions_router
    from raisebull.admin.routes_models import router as models_router
    from raisebull.admin.routes_chat import router as chat_router
    from raisebull.admin.routes_audit import router as audit_router

    app.include_router(status_router)
    app.include_router(context_router)
    app.include_router(skills_router)
    app.include_router(heartbeat_router)
    app.include_router(credentials_router)
    app.include_router(settings_router)
    app.include_router(permissions_router)
    app.include_router(models_router)
    app.include_router(chat_router)
    app.include_router(audit_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/integration/test_audit_api.py -v
```

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add src/raisebull/admin/routes_audit.py src/raisebull/admin/__init__.py tests/integration/test_audit_api.py
git commit -m "feat(audit): add GET /admin/api/audit endpoint

Date range filter (from/to ISO 8601 strings) is server-side; the
client applies action category filters over the returned batch.
Uses limit+1 probe to set truncated: true without a COUNT query.
Default limit 500, max 2000. Goes through auth_middleware automatically
via the /api/ path convention.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 11: Dashboard audit page + e2e tests

**Files:**
- Create: `src/raisebull/admin/static/pages/audit.html`
- Create: `src/raisebull/admin/static/pages/audit.js`
- Modify: `src/raisebull/admin/static/index.html` (add nav entry)
- Modify: `src/raisebull/admin/static/app.js` (router case)
- Create: `tests/e2e/audit.spec.ts`

- [ ] **Step 1: Inspect existing dashboard page patterns**

Before writing new files, read these two files to mirror their structure exactly:

```bash
cat src/raisebull/admin/static/pages/settings.html
cat src/raisebull/admin/static/pages/settings.js
cat src/raisebull/admin/static/index.html
cat src/raisebull/admin/static/app.js
```

Identify:
- How nav entries are declared in `index.html`
- How `app.js` loads page modules (look for a router or page loader pattern)
- Alpine.js component registration convention (e.g., `Alpine.data(...)` or inline `x-data="{...}"`)

- [ ] **Step 2: Write the failing e2e tests**

Create `tests/e2e/audit.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8766';
const PASSWORD = process.env.ADMIN_PASSWORD || 'testpass123';

async function login(page) {
  await page.goto(`${BASE}/admin/`);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForLoadState('networkidle');
}

test.describe('Audit Log page', () => {
  test('page loads with default 7-day data', async ({ page }) => {
    await login(page);
    // Navigate to Audit via nav link
    await page.click('a:has-text("Audit")');
    // Wait for the table to render (at least one row from the login itself)
    await expect(page.locator('table tbody tr')).toHaveCount(1, { timeout: 5000 });
    await expect(page.locator('table tbody tr')).toContainText('login.success');
  });

  test('category filter narrows results', async ({ page }) => {
    await login(page);
    await page.click('a:has-text("Audit")');
    await expect(page.locator('table tbody tr')).toContainText('login.success');

    // Uncheck the Auth → login.success checkbox
    await page.uncheck('input[type="checkbox"][value="login.success"]');
    await expect(page.locator('table tbody tr:has-text("login.success")')).toHaveCount(0);
  });
});
```

- [ ] **Step 3: Run the e2e tests (will fail since page does not exist)**

```bash
# Start a local uvicorn fixture (see CLAUDE.md Git Hooks for the exact pattern)
BASE_URL=http://127.0.0.1:8766 ADMIN_PASSWORD=testpass123 \
  npx playwright test tests/e2e/audit.spec.ts
```

Expected: 2 failures — "Audit" nav entry does not exist, `/admin/audit` page is empty.

- [ ] **Step 4: Create audit.html**

Create `src/raisebull/admin/static/pages/audit.html` (match the markup pattern from `settings.html`):

```html
<div x-data="auditPage()" x-init="init()" class="page-audit">
  <h2>Audit Log</h2>

  <div class="date-range">
    <label>From: <input type="date" x-model="fromDate"></label>
    <label>To: <input type="date" x-model="toDate"></label>
    <button @click="load()" :disabled="loading">Load</button>
  </div>

  <div class="category-filter">
    <template x-for="cat in categories" :key="cat.name">
      <div class="category-group">
        <strong x-text="cat.name"></strong>
        <template x-for="action in cat.actions" :key="action">
          <label>
            <input
              type="checkbox"
              :value="action"
              :checked="selectedActions.has(action)"
              @change="toggleAction(action)"
            >
            <span x-text="action"></span>
          </label>
        </template>
      </div>
    </template>
    <div class="bulk-actions">
      <button @click="selectAll()">All</button>
      <button @click="selectNone()">None</button>
    </div>
  </div>

  <template x-if="loading">
    <p>Loading...</p>
  </template>

  <template x-if="error">
    <p class="error" x-text="error"></p>
  </template>

  <template x-if="truncated">
    <p class="warning">
      ⚠ Truncated: showing first 500 rows. Narrow the date range to see all.
    </p>
  </template>

  <p class="summary">
    Showing <span x-text="filteredRows.length"></span> of
    <span x-text="fetchedRows.length"></span> entries
  </p>

  <table class="audit-table">
    <thead>
      <tr>
        <th>Time (UTC)</th>
        <th>Actor</th>
        <th>Action</th>
        <th>Target</th>
        <th>Before → After</th>
        <th>Source IP</th>
      </tr>
    </thead>
    <tbody>
      <template x-for="row in filteredRows" :key="row.id">
        <tr>
          <td x-text="formatTs(row.ts)"></td>
          <td x-text="row.actor"></td>
          <td x-text="row.action"></td>
          <td x-text="row.target || ''"></td>
          <td>
            <template x-if="row.before_val !== null || row.after_val !== null">
              <span>
                <span x-text="row.before_val || '∅'"></span>
                →
                <span x-text="row.after_val || '∅'"></span>
              </span>
            </template>
          </td>
          <td x-text="row.source_ip || ''"></td>
        </tr>
      </template>
    </tbody>
  </table>
</div>
```

- [ ] **Step 5: Create audit.js**

Create `src/raisebull/admin/static/pages/audit.js`:

```javascript
function auditPage() {
  return {
    fromDate: new Date(Date.now() - 7 * 86400e3).toISOString().slice(0, 10),
    toDate: new Date().toISOString().slice(0, 10),
    fetchedRows: [],
    truncated: false,
    loading: false,
    error: null,

    categories: [
      { name: 'Auth',      actions: ['login.success', 'login.fail'] },
      { name: 'Dashboard', actions: ['settings.put', 'session.delete'] },
      { name: 'Internal',  actions: ['internal.heartbeat', 'internal.nightly_compact', 'internal.discord_push'] },
      { name: 'Scheduler', actions: ['scheduler.heartbeat', 'scheduler.nightly_compact', 'scheduler.discord_push'] },
      { name: 'LINE',      actions: ['line.signature_fail'] },
    ],

    selectedActions: new Set([
      'login.success', 'login.fail',
      'settings.put', 'session.delete',
      'internal.heartbeat', 'internal.nightly_compact', 'internal.discord_push',
      'scheduler.heartbeat', 'scheduler.nightly_compact', 'scheduler.discord_push',
      'line.signature_fail',
    ]),

    get filteredRows() {
      return this.fetchedRows.filter(r => this.selectedActions.has(r.action));
    },

    async load() {
      this.loading = true;
      this.error = null;
      try {
        const from = `${this.fromDate}T00:00:00Z`;
        const to = `${this.toDate}T23:59:59Z`;
        const res = await fetch(
          `/admin/api/audit?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=500`
        );
        if (!res.ok) {
          this.error = (await res.json()).error || `HTTP ${res.status}`;
          return;
        }
        const data = await res.json();
        this.fetchedRows = data.rows || [];
        this.truncated = !!data.truncated;
      } catch (e) {
        this.error = String(e);
      } finally {
        this.loading = false;
      }
    },

    toggleAction(action) {
      if (this.selectedActions.has(action)) {
        this.selectedActions.delete(action);
      } else {
        this.selectedActions.add(action);
      }
      // Force Alpine reactivity on Set mutation
      this.selectedActions = new Set(this.selectedActions);
    },

    selectAll() {
      this.selectedActions = new Set(
        this.categories.flatMap(c => c.actions)
      );
    },

    selectNone() {
      this.selectedActions = new Set();
    },

    formatTs(ts) {
      if (!ts) return '';
      // "2026-04-08T03:42:11.123456+00:00" → "04-08 03:42 UTC"
      return ts.slice(5, 10) + ' ' + ts.slice(11, 16) + ' UTC';
    },

    init() {
      this.load();
    },
  };
}
```

- [ ] **Step 6: Add nav entry to index.html**

In `src/raisebull/admin/static/index.html`, find the existing nav list (should contain entries for Status, Settings, Credentials, Context, Skills, Heartbeat, Permissions, Chat) and add a new entry for Audit following the exact same pattern used by the others. The href / click handler should target the `audit` page. Example if the nav is a list of `<a>` tags:

```html
<a href="#/audit" @click.prevent="page = 'audit'">Audit</a>
```

Match whatever router convention `app.js` uses — do NOT invent a new one. If the page modules are loaded dynamically, register `audit` alongside the existing cases.

- [ ] **Step 7: Add router case to app.js**

In `src/raisebull/admin/static/app.js`, find where the existing pages are registered in the router / page loader, and add `audit` to the list. The exact code depends on the current pattern:

- If there's a `switch (page)` statement, add `case 'audit': ...`
- If there's an array/object of pages like `{ status: 'pages/status.html', settings: 'pages/settings.html', ... }`, add `audit: 'pages/audit.html'`
- If there's a `<script src="pages/settings.js">`-style include list, add `<script src="pages/audit.js">` to `index.html` too

- [ ] **Step 8: Run the e2e tests to verify they pass**

```bash
BASE_URL=http://127.0.0.1:8766 ADMIN_PASSWORD=testpass123 \
  npx playwright test tests/e2e/audit.spec.ts
```

Expected: 2 passed

- [ ] **Step 9: Run the full fast test suite to confirm nothing regressed**

```bash
uv run pytest tests/unit tests/integration tests/test_audit_scheduler.py tests/test_main.py tests/test_session.py tests/test_recovery.py tests/test_runner.py tests/test_discord_bot.py -q
```

Expected: `319 passed` (original 293 + 26 new).

- [ ] **Step 10: Commit**

```bash
git add src/raisebull/admin/static/pages/audit.html src/raisebull/admin/static/pages/audit.js src/raisebull/admin/static/index.html src/raisebull/admin/static/app.js tests/e2e/audit.spec.ts
git commit -m "feat(audit): add dashboard Audit page with filters

Alpine.js page with server-side date range filter (re-fetches on Load)
and client-side action category filter (pure JS over fetchedRows).
5 category groups (Auth / Dashboard / Internal / Scheduler / LINE)
with 11 checkboxes + All/None bulk actions. Default: last 7 days,
all actions checked.

Truncation banner appears when server returns truncated: true.
Timestamps rendered in UTC (no local-time conversion to avoid DST).

2 Playwright e2e tests: page loads with login row visible, and
unchecking login.success filter hides that row.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 12: Final verification + push

**Files:** none

- [ ] **Step 1: Run the full fast suite (pre-push equivalent)**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
uv run pytest tests/unit tests/integration tests/ -q --ignore=tests/smoke --ignore=tests/e2e
```

Expected: `319 passed` (original 293 + 26 new audit tests)

- [ ] **Step 2: Run the LLM-free Playwright subset**

```bash
SKIP_LLM_E2E=1 npx playwright test
```

Expected: `21 passed` (original 19 + 2 new audit e2e tests)

- [ ] **Step 3: Push the branch**

```bash
git push -u origin feat/audit-logs
```

The pre-push hook (`scripts/git-hooks/pre-push`) auto-runs the fast suite + LLM-free e2e subset. If it fails, fix the issue in a new commit — do NOT `--no-verify` or `--amend`.

- [ ] **Step 4: Optional — merge fast-forward to main**

Only after human review of the commit history:

```bash
git checkout main
git merge --ff-only feat/audit-logs
git push origin main
```

- [ ] **Step 5: Optional — rebuild bull-daniu on samantha-wsl**

Follow the existing deployment procedure in CLAUDE.md. The `CREATE TABLE IF NOT EXISTS` will self-heal `sessions.db` on first startup. No manual migration needed.

---

## Spec Coverage Checklist

- **Motivation (spec §1)** — implicit in commits + audit rows appear on real usage
- **Schema (spec §4)** — Task 1 (table + 2 indexes)
- **AuditLog class API (spec §6)** — Task 1 (full class implementation)
- **login.success / login.fail / password-never-logged (spec §5, §7.1)** — Task 3
- **settings.put diff (spec §5, §7.2)** — Task 4
- **session.delete (spec §5, §7.3)** — Task 5
- **internal.heartbeat / internal.nightly_compact / internal.discord_push (spec §5, §7.4)** — Task 6
- **line.signature_fail (spec §5, §7.5)** — Task 7
- **scheduler.heartbeat / scheduler.nightly_compact (spec §5, §7.6)** — Task 8
- **scheduler.discord_push with truncated message (spec §5, §7.7)** — Task 9
- **GET /admin/api/audit (spec §8)** — Task 10
- **Dashboard page with date + category filters (spec §9)** — Task 11
- **~26 new tests (spec §10)** — 6 unit (Task 1) + 10 hooks (3 login + 3 settings + 2 session.delete + 4 internal = Tasks 3-6) + 4 API (Task 10) + 3 scheduler (Tasks 8-9) + 1 LINE (Task 7) + 2 e2e (Task 11) = 26 ✓
- **Migration — no ALTER TABLE (spec §11)** — Task 1 uses `CREATE TABLE IF NOT EXISTS`
- **Rollout — feat/audit-logs branch + TDD (spec §12)** — All tasks follow RED → GREEN → commit

Open questions from spec §13 resolved:
- Heartbeat.py import strategy → **explicit parameter threading** (Task 8)
- Test fixture scope → **function-scoped `:memory:`** (Task 1 + 3 + 10)
- E2E seeding → **no seed step; rely on the login row from `login()` fixture** (Task 11)
