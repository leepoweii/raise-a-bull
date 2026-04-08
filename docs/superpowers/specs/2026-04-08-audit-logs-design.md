# Audit Logs — Design Spec

**Date:** 2026-04-08
**Scope:** `docs/future-improvements.md` item 6 — Option B (lightweight SQLite audit log) + dashboard viewer page
**Status:** Draft — awaiting user approval

---

## 1. Motivation

raise-a-bull currently has no structured "who did what when" trail. Python `logger.info(...)` lines are unstructured, uvicorn access logs lack action semantics, and Claude Code `.jsonl` conversation history tracks dialog but not admin actions. This makes three classes of operational questions hard to answer:

- **Security forensics** — "A weird message appeared in #daily-ops at 03:42 — did it come from a real user, a scheduled heartbeat push, or someone running `/internal/discord/push`? From where?"
- **Settings drift debugging** — "Why is `nightly_compact_threshold` at 9999 instead of 50000? Who changed it, when, and from which IP?"
- **Cron accountability** — "Did nightly compact actually run last night, or was the cron job silent? Was the last heartbeat tick manually fired by `docker exec` or by APScheduler?"

This spec implements Option B from `docs/future-improvements.md` (lightweight audit table in `sessions.db`) plus a dashboard viewer page with date range + category filters.

Option C (retention policy, pluggable backends, export formats) remains deferred until a real compliance need arises.

## 2. Goals & Non-Goals

### Goals
- Capture 11 distinct action types across dashboard auth, settings mutations, session deletion, LINE webhook verification, manual `/internal/*` triggers, and APScheduler cron jobs
- Persist to the existing `sessions.db` SQLite file (no new DB file, no new volume)
- Expose a read-only dashboard page (`/admin/audit`) with server-side date range filtering and client-side category filtering
- Record source IP for every action that has one (loopback IPs are still useful — they distinguish manual `docker exec` triggers from in-process scheduler calls which have `source_ip=NULL`)
- Never log secret material (passwords, access tokens, API keys) in any audit field

### Non-Goals (deferred to Option C)
- Retention policy / auto-pruning by row count or age
- Multi-backend export (JSONL files, syslog, external SIEM)
- Search/text-content filter (beyond date range + action category)
- Per-LINE-message reply logging (too noisy; Claude Code `.jsonl` already captures full dialog)
- Discord bot message logging (gateway WebSocket has no per-message IP, and bot replies are high-volume)
- Credentials PUT hook (out of scope; would require redaction design)

## 3. Architecture

```
src/raisebull/
├── audit.py                  ← NEW: AuditLog class (aiosqlite, sessions.db)
├── main.py                   ← wire lifespan + _audit_log global + /internal/* hooks
│                              + webhook_line signature hook + heartbeat_push callback hook
├── heartbeat.py              ← scheduler.heartbeat + scheduler.nightly_compact hooks
└── admin/
    ├── __init__.py           ← pass audit_log into sub-app state
    ├── auth.py               ← login.success / login.fail hooks
    ├── routes_settings.py    ← settings.put hook (diff, one row per changed key)
    ├── routes_chat.py        ← session.delete hook
    ├── routes_audit.py       ← NEW: GET /api/audit?from=&to=&limit=
    └── static/
        ├── index.html        ← add Audit nav entry
        ├── app.js            ← add audit router case
        └── pages/
            ├── audit.html    ← NEW: checkbox groups + date picker + table
            └── audit.js      ← NEW: Alpine.js component
```

### Initialization Flow

```
lifespan startup:
  _sessions = SessionStore(db_path=sessions.db); await _sessions.init()
  _audit_log = AuditLog(db_path=sessions.db); await _audit_log.init()
  _admin_app.state.sessions = _sessions
  _admin_app.state.audit_log = _audit_log    ← admin routes access via request.app.state
  # _audit_log module-level global is used directly by /internal/* routes in main.py

lifespan shutdown:
  await _audit_log.close()
  await _sessions.close()
```

### AuditLog Access Patterns

- **Admin routes** (`auth.py`, `routes_settings.py`, `routes_chat.py`, `routes_audit.py`): use `getattr(request.app.state, "audit_log", None)` so tests that skip full lifespan don't crash. This mirrors the existing `sessions` access pattern in `routes_chat.py:45`.
- **Internal/main routes** (`main.py` `/internal/*` handlers, `webhook_line` signature path, `heartbeat_push` callback): use the module-level `_audit_log` global, same as the existing `_sessions` global.
- **Scheduler routes** (`heartbeat.py` `nightly_compact()` and `run_event_check()` entry points): import `_audit_log` lazily from `main` or pass it in through an existing call chain — TBD at writing-plans time based on which pattern is minimal.

### Concurrency / SQLite Connection

`AuditLog` opens its own `aiosqlite.Connection` to the same `sessions.db` file. This mirrors the existing pattern where `SessionStore` and `MessageBuffer` each hold independent connections to the same DB. SQLite + aiosqlite handle multiple concurrent connections correctly under the current asyncio workload (no WAL mode needed — writes are low-volume and short-lived).

## 4. Schema

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,       -- ISO 8601 UTC, e.g. "2026-04-08T03:42:11.123456+00:00"
    actor       TEXT NOT NULL,       -- 'admin' | 'unknown' | 'system' | 'scheduler'
    action      TEXT NOT NULL,       -- see Action Catalog below
    target      TEXT,                -- key name / channel_id / session_id (NULL if N/A)
    before_val  TEXT,                -- raw string, NULL for non-mutation actions
    after_val   TEXT,                -- raw string
    source_ip   TEXT                 -- request.client.host (NULL for in-process/scheduler actions)
);
CREATE INDEX IF NOT EXISTS idx_audit_log_ts     ON audit_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
```

**Format decisions:**

- `before_val` / `after_val` store **raw strings**, not JSON-encoded strings. Rationale: settings values are already strings (`routes_settings.py:130`: `current[key] = str(body[key])`), so `json.dumps("50000")` would add useless double quotes that clutter `sqlite3` CLI output. A future reader can still JSON-parse if needed, but the common case (`sqlite3 sessions.db "SELECT target, before_val, after_val FROM audit_log"`) reads cleanly.
- `ts` uses `datetime.now(timezone.utc).isoformat()` so SQLite lex-sort on the TEXT column is also chronological — no separate epoch column needed.
- Timestamps are always UTC. Dashboard UI displays in UTC for the initial version (no local-time conversion) to avoid DST edge cases.

## 5. Action Catalog (11 types)

| Action | Actor | Target | before_val | after_val | source_ip | Hook location |
|--------|-------|--------|-----------|-----------|-----------|---------------|
| `login.success` | `admin` | NULL | NULL | NULL | request.client | `admin/auth.py` `login_endpoint` |
| `login.fail` | `unknown` | NULL | NULL | NULL | request.client | `admin/auth.py` `login_endpoint` |
| `settings.put` | `admin` | key name | old raw value | new raw value | request.client | `admin/routes_settings.py` `put_settings` |
| `session.delete` | `admin` | session_id | NULL | NULL | request.client | `admin/routes_chat.py` `delete_session` |
| `line.signature_fail` | `unknown` | NULL | NULL | NULL | request.client | `main.py` `webhook_line` (on `InvalidSignatureError`) |
| `internal.heartbeat` | `system` | NULL | NULL | NULL | loopback | `main.py` `/internal/heartbeat/trigger` |
| `internal.nightly_compact` | `system` | NULL | NULL | NULL | loopback | `main.py` `/internal/nightly-compact/trigger` |
| `internal.discord_push` | `system` | channel_id | NULL | message[:200] | loopback | `main.py` `/internal/discord/push` |
| `scheduler.heartbeat` | `scheduler` | NULL | NULL | NULL | NULL | `heartbeat.py` APScheduler `run_event_check` entry |
| `scheduler.nightly_compact` | `scheduler` | NULL | NULL | NULL | NULL | `heartbeat.py` APScheduler `nightly_compact` entry |
| `scheduler.discord_push` | `scheduler` | channel_name | NULL | message[:200] | NULL | `main.py` `heartbeat_push` callback (after successful `channel.send`) |

**Design decisions:**

- `internal.*` and `scheduler.*` are kept as separate action names (not consolidated via actor) because the forensics question "did cron run last night vs did someone `docker exec` a manual trigger" is answered by a single `WHERE action LIKE 'scheduler.%'` query. Consolidating to `heartbeat.tick` + actor filter would force a two-column `WHERE`, which is less obvious in `sqlite3` CLI usage.
- `internal.discord_push` and `scheduler.discord_push` both record `after_val = message[:200]` (first 200 characters) — this is the whole point of audit ("what was pushed to #daily-ops at 03:42?"). 200 chars is enough to identify the content without bloating the DB.
- `settings.put` records **one row per changed key**. A PUT body with 3 keys where only 2 actually differ from current produces 2 audit rows, not 3. This keeps the log clean and makes "when was `nightly_compact_threshold` last changed" a precise query.
- `login.fail` records the attempted IP but **never** the password attempt. The payload never touches `record()`.
- `internal.localhost_rejection` (403 from `_require_localhost`) is **not** audited. The gate runs before the handler, so no hook point exists. If this becomes important, a separate middleware-level audit can be added in Option C.
- `session.delete` with a 404 (session not found) is **not** audited — the handler returns early before the audit call.
- `settings.put` with validation failure (400) is **not** audited — the rejection happens before the diff loop.

## 6. AuditLog Class

`src/raisebull/audit.py`:

```python
from __future__ import annotations

import aiosqlite
from datetime import datetime, timezone


class AuditLog:
    """Append-only audit log backed by SQLite.

    Lifecycle mirrors SessionStore: construct with db_path, await init() to
    open connection + create table, await close() to release connection.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def init(self) -> None:
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
        target: str | None = None,
        before_val: str | None = None,
        after_val: str | None = None,
        source_ip: str | None = None,
    ) -> None:
        """Append one audit row. Never raises on normal input.

        `action` and `actor` are free strings at the class level (the catalog
        is enforced by callers). This keeps AuditLog reusable if a future
        hook needs a new action type without touching this file.
        """
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
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Return rows matching the date range, newest first.

        `from_ts` / `to_ts` are ISO 8601 strings. Pass `limit + 1` from the
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

## 7. Hook Implementation Details

### 7.1 `admin/auth.py` `login_endpoint`

```python
async def login_endpoint(request: Request):
    body = await request.json()
    password = body.get("password", "")
    expected = _get_password()
    audit_log = getattr(request.app.state, "audit_log", None)
    source_ip = request.client.host if request.client else None

    if not expected or not hmac.compare_digest(password, expected):
        if audit_log:
            await audit_log.record("login.fail", actor="unknown", source_ip=source_ip)
        return JSONResponse({"error": "Invalid password"}, status_code=401)

    if audit_log:
        await audit_log.record("login.success", actor="admin", source_ip=source_ip)
    response = JSONResponse({"ok": True})
    create_session_cookie(response)
    return response
```

**Security note:** the `body` dict is never passed to `record()`. Only the boolean result (success/fail) and IP are recorded.

### 7.2 `admin/routes_settings.py` `put_settings`

Add the diff + record loop **after** validation passes and **after** the file write succeeds:

```python
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

if audit_log and changes:
    for key, before, after in changes:
        await audit_log.record(
            "settings.put", actor="admin", target=key,
            before_val=before, after_val=after, source_ip=source_ip,
        )
return {"ok": True}
```

**Order matters:** record is after `os.replace` succeeds. If the file write fails the audit log stays clean.

### 7.3 `admin/routes_chat.py` `delete_session`

Insert after the in-memory/DB cleanup, before `return {"ok": True}`:

```python
audit_log = getattr(request.app.state, "audit_log", None)
if audit_log:
    await audit_log.record(
        "session.delete", actor="admin", target=session_id,
        source_ip=request.client.host if request.client else None,
    )
```

The 404 branch (`return JSONResponse({"error": "session not found"}, status_code=404)`) returns before this point, so no audit row for not-found deletes.

### 7.4 `main.py` `/internal/*` handlers

Use the module-level `_audit_log` global (same pattern as `_sessions`):

```python
@app.post("/internal/heartbeat/trigger")
async def heartbeat_trigger(request: Request) -> dict[str, Any]:
    _require_localhost(request)
    if _audit_log:
        await _audit_log.record(
            "internal.heartbeat", actor="system",
            source_ip=request.client.host if request.client else None,
        )
    asyncio.create_task(run_event_check(_runner, _sessions, push_fn=_heartbeat_push))
    return {"ok": True, "message": "heartbeat tick started"}
```

`nightly_compact_trigger` uses `action="internal.nightly_compact"`. `discord_push` uses `action="internal.discord_push"`, `target=req.channel_id`, and `after_val=req.message[:200]`.

**Order:** record is called AFTER `_require_localhost()` passes (403 rejections not audited) but BEFORE the background task is spawned (so even if the task fails, the audit trail shows "someone tried").

### 7.5 `main.py` `webhook_line` signature handler

```python
try:
    events = parser.parse(body_text, signature)
except InvalidSignatureError:
    if _audit_log:
        await _audit_log.record(
            "line.signature_fail", actor="unknown",
            source_ip=request.client.host if request.client else None,
        )
    raise HTTPException(status_code=400, detail="Invalid signature")
```

### 7.6 `heartbeat.py` scheduler entry points

At the top of `nightly_compact()` (after the `_nightly_lock` acquisition) and `run_event_check()` (called by APScheduler):

```python
# nightly_compact entry
if _audit_log:
    await _audit_log.record("scheduler.nightly_compact", actor="scheduler")
```

```python
# run_event_check entry (APScheduler tick)
if _audit_log:
    await _audit_log.record("scheduler.heartbeat", actor="scheduler")
```

These functions are called by APScheduler with no HTTP request context, so `source_ip=NULL`.

**Import strategy:** `heartbeat.py` currently does not import from `main`. The cleanest wiring is to add an optional `audit_log: AuditLog | None = None` parameter to `start_heartbeat()`, `run_event_check()`, and `nightly_compact()`, passed from `main.py` lifespan. This avoids a circular import. The exact call-site threading is a writing-plans detail.

### 7.7 `main.py` `heartbeat_push` callback

After the successful `channel.send`:

```python
async def heartbeat_push(channel_name: str, message: str) -> None:
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
        if _audit_log:
            await _audit_log.record(
                "scheduler.discord_push", actor="scheduler",
                target=channel_name, after_val=message[:200],
            )
    else:
        logger.warning("Heartbeat push: #%s not found", channel_name)
```

## 8. Read API — `GET /admin/api/audit`

New router `src/raisebull/admin/routes_audit.py`:

```python
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/audit")

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 2000


@router.get("")
async def list_audit(request: Request):
    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is None:
        return JSONResponse({"error": "audit log not initialized"}, status_code=503)

    qp = request.query_params
    from_ts = qp.get("from")
    to_ts = qp.get("to")

    try:
        limit = int(qp.get("limit", _DEFAULT_LIMIT))
    except ValueError:
        return JSONResponse({"error": "limit must be an integer"}, status_code=400)
    if limit < 1 or limit > _MAX_LIMIT:
        return JSONResponse(
            {"error": f"limit must be between 1 and {_MAX_LIMIT}"},
            status_code=400,
        )

    rows = await audit_log.list_recent(from_ts=from_ts, to_ts=to_ts, limit=limit + 1)
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

**Key design points:**

- **`limit + 1` probe:** SQL fetches one extra row to detect if more exist beyond the requested limit. Response sets `truncated: true` so the UI can show a "narrow your date range" banner without a separate COUNT query.
- **Default 500, max 2000:** balances memory footprint of the Alpine.js reactive array against the typical "last 7 days" query (which in practice yields far fewer than 500 rows).
- **`from_ts` / `to_ts` are ISO 8601 strings:** SQLite TEXT comparison on ISO 8601 is chronologically correct, so no datetime parsing is needed. The UI submits strings like `2026-04-08T00:00:00Z`.
- **Newest first:** `ORDER BY ts DESC` so the default 500-row fetch naturally captures the most recent activity.
- **Auth:** the endpoint path `/api/audit` matches `auth_middleware`'s `"/api/" in path and not path.endswith("/api/auth")` rule, so the existing HMAC cookie check applies automatically. No special wiring needed.
- **Registration:** add `from raisebull.admin.routes_audit import router as audit_router` and `app.include_router(audit_router)` to `admin/__init__.py` alongside the existing 9 routers.

## 9. Dashboard Page

New files `admin/static/pages/audit.html` and `admin/static/pages/audit.js`. Navigation entry added to `admin/static/index.html`. Router case added to `admin/static/app.js`.

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Audit Log                                                   │
├─────────────────────────────────────────────────────────────┤
│ Date range:  [2026-04-01] → [2026-04-08]  [Load]           │
│                                                             │
│ Filter by category:                                         │
│  Auth         [x] login.success  [x] login.fail            │
│  Dashboard    [x] settings.put   [x] session.delete        │
│  Internal     [x] heartbeat  [x] nightly_compact  [x] push │
│  Scheduler    [x] heartbeat  [x] nightly_compact  [x] push │
│  LINE         [x] signature_fail                            │
│                                                             │
│  [All]  [None]                                              │
├─────────────────────────────────────────────────────────────┤
│ Showing 127 of 127 entries (7 days)                         │
│ ⚠ Truncated: 500 rows returned, narrow date range to see all│
├─────────────────────────────────────────────────────────────┤
│ TS                 ACTOR      ACTION              TARGET    │
│ 04-08 03:42 UTC    admin      settings.put        nightly…  │
│   50000 → 9999  · from 192.168.1.5                         │
│                                                             │
│ 04-08 03:00 UTC    scheduler  scheduler.nightly_…           │
│                                                             │
│ 04-07 23:42 UTC    scheduler  scheduler.discord_…  #daily…  │
│   "早安！今天是 04-07 週一…"                                │
└─────────────────────────────────────────────────────────────┘
```

### Alpine.js Component (`audit.js`)

```js
function auditPage() {
  return {
    fromDate: new Date(Date.now() - 7 * 86400e3).toISOString().slice(0, 10),
    toDate: new Date().toISOString().slice(0, 10),
    fetchedRows: [],
    truncated: false,
    loading: false,
    error: null,

    categories: [
      { name: 'Auth',       actions: ['login.success', 'login.fail'] },
      { name: 'Dashboard',  actions: ['settings.put', 'session.delete'] },
      { name: 'Internal',   actions: ['internal.heartbeat', 'internal.nightly_compact', 'internal.discord_push'] },
      { name: 'Scheduler',  actions: ['scheduler.heartbeat', 'scheduler.nightly_compact', 'scheduler.discord_push'] },
      { name: 'LINE',       actions: ['line.signature_fail'] },
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
        const to   = `${this.toDate}T23:59:59Z`;
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
      if (this.selectedActions.has(action)) this.selectedActions.delete(action);
      else this.selectedActions.add(action);
      this.selectedActions = new Set(this.selectedActions); // force reactivity
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
      return ts ? ts.replace('T', ' ').slice(0, 16) + ' UTC' : '';
    },

    init() { this.load(); },
  };
}
```

### Interaction Model

- **Initial load:** last 7 days, all 11 actions checked, server fetches once
- **Date range change + [Load]:** new `fetch()` with `from`/`to` query params → replaces `fetchedRows`
- **Category checkbox change:** pure JS filter via `filteredRows` computed property → no re-fetch
- **Truncation warning:** when server returns `truncated: true`, a banner at the top reads "Truncated — showing 500 of ≥501 entries. Narrow date range to see all."
- **UTC display:** timestamps render as `04-08 03:42 UTC` for the initial version. Local time / relative time rendering is a future nicety.

## 10. Testing Strategy

Total: **~26 new tests**, tracking the existing pyramid (`293 fast + 16 smoke + 19 e2e` in CLAUDE.md).

### Unit tests — `tests/unit/test_audit.py` (~6 tests)

In-memory SQLite (`:memory:`), tests `AuditLog` class in isolation:

1. `test_init_creates_table` — after `init()` a raw SQL INSERT succeeds
2. `test_record_round_trip` — `record()` then `list_recent()` returns the exact fields
3. `test_record_with_all_nulls` — target/before/after/source_ip all None does not raise
4. `test_list_recent_date_range_filter` — from_ts/to_ts correctly bound the query
5. `test_list_recent_ordered_desc` — three inserts in sequence → `list_recent` returns newest first
6. `test_list_recent_limit` — limit=5 returns at most 5 rows

### Integration tests — `tests/integration/test_audit_hooks.py` (~10 tests)

Full admin sub-app via `ASGITransport` + `httpx.AsyncClient`. Each test covers one HTTP hook point:

1. `test_login_success_recorded` — correct password → 1 row `login.success`, actor=admin, source_ip present
2. `test_login_fail_recorded` — wrong password → 1 row `login.fail`, actor=unknown
3. `test_login_does_not_log_password` — after login fail attempt with a unique password string, `SELECT * FROM audit_log` contains zero occurrences of that string
4. `test_settings_put_logs_only_changed_keys` — PUT body with 3 keys where 1 matches current → 2 audit rows
5. `test_settings_put_no_change_no_audit` — PUT with all-same values → 0 audit rows
6. `test_settings_put_validation_fail_no_audit` — invalid `nightly_compact_threshold=0` → 400 + 0 audit rows
7. `test_session_delete_recorded` — DELETE existing session → 1 row `session.delete`, target=session_id
8. `test_session_delete_404_no_audit` — DELETE nonexistent → 404 + 0 audit rows
9. `test_internal_heartbeat_trigger_recorded` — POST /internal/heartbeat/trigger via ASGITransport (loopback) → 1 row
10. `test_internal_localhost_rejection_no_audit` — simulate non-loopback client → 403 + 0 audit rows

### Integration tests — `tests/integration/test_audit_api.py` (~4 tests)

Tests `GET /admin/api/audit`:

1. `test_list_audit_requires_auth` — no cookie → 401
2. `test_list_audit_returns_rows_desc` — seed 3 rows → GET returns them newest first
3. `test_list_audit_date_range_filter` — seed 5 rows spanning 10 days, query middle 3 days → only 3 rows
4. `test_list_audit_truncated_flag` — seed 501 rows, GET `limit=500` → `rows.length == 500` and `truncated: true`

### Scheduler tests — `tests/test_audit_scheduler.py` (~3 tests)

These hook into `heartbeat.py` entry points, not HTTP:

1. `test_scheduler_heartbeat_recorded` — direct call to `run_event_check(..., audit_log=al)` → 1 row `scheduler.heartbeat`
2. `test_scheduler_nightly_compact_recorded` — direct call to `nightly_compact(..., audit_log=al)` → 1 row `scheduler.nightly_compact`
3. `test_scheduler_discord_push_records_truncated_message` — call `heartbeat_push` (monkeypatch `channel.send`) with a 500-char message → audit row has exactly 200-char `after_val`

### LINE test — `tests/integration/test_audit_line.py` (~1 test)

1. `test_line_signature_fail_recorded` — POST /webhook/line with invalid signature header → 1 row `line.signature_fail`

### E2E tests — `tests/e2e/audit.spec.ts` (~2 tests, LLM-free, runs in pre-push hook)

1. **Page loads with default data** — login → navigate to Audit → table shows at least 1 row (the login.success that just happened)
2. **Category filter narrows results** — click off "Auth" checkbox → `login.success` row disappears from table

### Test Count Summary

| Level | Count |
|-------|-------|
| Unit | 6 |
| Integration (hooks) | 10 |
| Integration (API) | 4 |
| Integration (scheduler) | 3 |
| Integration (LINE) | 1 |
| E2E (Playwright) | 2 |
| **Total new tests** | **~26** |

New baseline: `319 fast + 16 smoke + 21 e2e`.

## 11. Migration & Backfill

- **No migration needed for existing DBs:** `CREATE TABLE IF NOT EXISTS` adds the table on first `AuditLog.init()`. The existing `sessions.db` on samantha-wsl just grows one new table. No `ALTER TABLE` needed (audit_log is a fresh table, not an extension of sessions).
- **No backfill:** the audit log starts empty on first deploy. Historical actions cannot be reconstructed from uvicorn logs or Claude `.jsonl` — that's the gap this feature addresses going forward.

## 12. Rollout Plan

This work happens on a dedicated branch off main following the CLAUDE.md workflow:

1. Branch from main: `git checkout -b feat/audit-logs`
2. Follow TDD cycle per hook point (RED → GREEN → commit) — each commit is small and reviewable
3. Pre-push hook runs 319 fast + 21 e2e on every push
4. After all tasks green locally, merge fast-forward to main
5. Rebuild `bull-daniu` on samantha-wsl to pick up the new table and dashboard page (the `CREATE TABLE IF NOT EXISTS` self-heals on startup)

No feature flag or gradual rollout needed — the audit log is fully additive (no existing behavior changes), and if `_audit_log` fails to initialize, all hooks fall through the `if audit_log:` guard.

## 13. Open Questions (for writing-plans)

These are writing-plans-level details, not spec-level ambiguities. Listed here so the implementation plan can address each:

- **heartbeat.py import strategy:** pass `AuditLog` through `start_heartbeat()` call chain vs. lazy import from `main`. Prefer explicit parameter threading for testability.
- **Test seed strategy:** each hook integration test needs a fresh `audit_log` fixture — decide between function-scoped `AuditLog(":memory:")` and module-scoped with truncation. Function-scoped is simpler.
- **E2E data seeding:** the Playwright test needs at least one audit row to exist. Simplest approach is to have the test log in first (which creates a `login.success` row) and verify that row appears. No separate seed step needed.

---

**End of spec.** Ready for writing-plans on approval.
