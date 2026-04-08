# Audit Log Follow-ups Implementation Plan (N1 + N2 + N3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three follow-up gaps from the `feat/audit-logs` work (merged to main on 2026-04-08):

- **N1 — credentials audit hooks**: Close the biggest security forensics gap. Currently, changing an API key leaves zero audit trail. Add hooks for `credentials.create` + `credentials.put` + `credentials.delete` with redacted values (never log the actual secret).
- **N2 — Fix `nightly_compact_threshold round-trips` e2e flake**: A pre-existing e2e test on main that was already failing before audit log work. Blocks future Settings branch pre-push hook runs with false signal.
- **N3 — `_normalize_iso` symmetry cleanup**: Tech debt from feat/audit-logs. Frontend sends `Z` suffix, backend stores `+00:00`, a helper normalizes at the API boundary. Cleaner: have frontend send `+00:00` directly, delete the helper. Eliminates the asymmetry.

**Architecture:** All three are independent, no cross-dependencies. Single branch `feat/audit-log-follow-ups` with 3 distinct commits (one per task). Total scope ≈ half a session.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, Alpine.js, Playwright. Same stack as the existing audit log code.

**Spec reference:** `docs/superpowers/specs/2026-04-08-audit-logs-design.md` (the original audit log design — items 7d, 9c/9d, 11 in `docs/future-improvements.md` are what this plan addresses).

**Plan reference:** `docs/superpowers/plans/2026-04-08-audit-logs.md` (the original 12-task plan; Task 3/4/5/6/7/8/9 are worth reading for the hook pattern before starting N1).

**Branch:** `feat/audit-log-follow-ups` off `main`. Create before starting:
```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git checkout main && git pull --ff-only origin main
git checkout -b feat/audit-log-follow-ups
```

---

## Context — what already exists

The audit log base is fully shipped on main:

- `src/raisebull/audit.py` — `AuditLog` class with aiosqlite backend
- 11 action types recorded: `login.success/fail`, `settings.put`, `session.delete`, `line.signature_fail`, `internal.heartbeat/nightly_compact/discord_push`, `scheduler.heartbeat/nightly_compact/discord_push`
- Dashboard page at `/admin/#/audit` with server-side date filter + client-side category filter (5 groups, 11 checkboxes)
- `GET /admin/api/audit?from=&to=&limit=` with `_normalize_iso()` helper (the thing N3 deletes)
- 28 tests (6 unit + 17 integration + 3 scheduler + 2 e2e)
- Production deployed to `bull-daniu` on samantha-wsl with `CREATE TABLE IF NOT EXISTS` auto-migration

The **hook pattern** used consistently across all existing actions:

```python
audit_log = getattr(request.app.state, "audit_log", None)
source_ip = request.client.host if request.client else None

# ... do the actual route work ...

if audit_log is not None:
    await audit_log.record(
        "action.name",
        actor="admin",
        target=some_identifier,
        before_val=old_or_none,
        after_val=new_or_none,
        source_ip=source_ip,
    )
```

Record calls happen **AFTER** the route's success path (so failed writes don't produce phantom audit rows) but **BEFORE** the final `return` (so the response body isn't delayed by anything downstream).

---

## File Map

### New files
None — this plan only extends existing files.

### Modified files

| File | Task | What changes |
|------|------|--------------|
| `src/raisebull/admin/routes_credentials.py` | N1 | Add audit hook to `create_credential`, `update_credential`, `delete_credential`. Lookup `key_name` before mutations where needed. |
| `tests/integration/test_audit_hooks.py` | N1 | Append `TestCredentialsHooks` class with ~5 tests |
| `tests/e2e/dashboard.spec.ts` | N2 | Fix the flaky test at line 120 (`nightly_compact_threshold round-trips through save button`) — investigate and fix root cause |
| `src/raisebull/admin/routes_audit.py` | N3 | Delete `_normalize_iso()` helper + callsites |
| `src/raisebull/admin/static/pages/audit.js` | N3 | Send `+00:00` instead of `Z` in `load()` date query params |
| `tests/integration/test_audit_api.py` | N3 | Delete `test_list_audit_accepts_z_suffix` (behavior is gone) |

---

## Task 1 (N1): Credentials audit hooks

**Files:**
- Modify: `src/raisebull/admin/routes_credentials.py` (3 handlers)
- Modify: `tests/integration/test_audit_hooks.py` (new `TestCredentialsHooks` class)

### Design decisions

**Three new actions** (expanding N1 beyond just `credentials.put` to cover all mutating endpoints):

| Action | When | `target` | `before_val` | `after_val` |
|--------|------|----------|--------------|-------------|
| `credentials.create` | `POST /api/credentials` success | `key_name` from body | `NULL` | `"***<last 4>"` |
| `credentials.put` | `PUT /api/credentials/{id}` success | `key_name` looked up from DB | `NULL` (never old value) | `"***<last 4>"` (if `key_value` changed) OR `NULL` (if only `service` changed) |
| `credentials.delete` | `DELETE /api/credentials/{id}` success | `key_name` looked up before delete | `NULL` | `NULL` |

All three use `actor="admin"` + `source_ip=request.client.host`. The 404 branches of PUT/DELETE do NOT produce audit rows — they return early before the hook.

**Redaction rule:** `after_val = f"***{value[-4:]}"` if `len(value) >= 4`, else `"***"`. Never log the full value under any field.

**Why `before_val=NULL` even for updates:** Logging the old value would leak the previous credential to anyone who can read the audit log. Forensics only needs to know "who changed WHICH key WHEN from WHERE", not what the old value was.

**Out of scope:** `POST /api/credentials/test` endpoint. It receives raw `key_value` in the body to test a live API call. Auditing it risks leaking the value; and since it's read-only (doesn't mutate credentials), it has low forensics value. Skip it.

### Step 1.1: Write the failing tests

- [ ] Read `tests/integration/test_audit_hooks.py` to understand the existing fixture pattern (`audit_log`, `admin_app`, `client`, `_login`). These fixtures already wire `audit_log` into `create_admin_app`'s sub-app state.

- [ ] Append a new `TestCredentialsHooks` class at the bottom of `tests/integration/test_audit_hooks.py`:

```python
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
```

- [ ] Run the tests — expect failures:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
uv run pytest tests/integration/test_audit_hooks.py::TestCredentialsHooks -v
```

Expected: 6 failures (no hooks exist yet) OR 5 failures + 1 pass (the 404 test might trivially pass with 0 rows since there's no existing hook).

### Step 1.2: Add the hooks to routes_credentials.py

- [ ] Open `src/raisebull/admin/routes_credentials.py` and modify the three mutating handlers.

**Add a redaction helper near the top** (after imports):

```python
def _redact(value: str | None) -> str | None:
    """Return a redacted form of a credential value for audit logging.

    We record only the last 4 characters prefixed with '***' so operators
    can distinguish "this was changed" from "this was ROTATED to the same
    value" without ever storing the full secret. For values shorter than
    4 characters, redact entirely.
    """
    if value is None:
        return None
    if len(value) < 4:
        return "***"
    return f"***{value[-4:]}"
```

**Modify `create_credential`:**

```python
@router.post("")
async def create_credential(request: Request):
    body = await request.json()
    item = _get_table(request).create({
        "key_name": body["key_name"],
        "key_value": body["key_value"],
        "service": body.get("service", ""),
    })

    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is not None:
        await audit_log.record(
            "credentials.create",
            actor="admin",
            target=body["key_name"],
            before_val=None,
            after_val=_redact(body["key_value"]),
            source_ip=request.client.host if request.client else None,
        )
    return item
```

**Modify `update_credential`** — need to look up the `key_name` for the audit row, AND detect whether `key_value` actually changed so we can set `after_val` correctly:

```python
@router.put("/{cred_id}")
async def update_credential(cred_id: str, request: Request):
    body = await request.json()
    allowed = {"key_value", "service"}
    data = {k: v for k, v in body.items() if k in allowed}
    if not data:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    # Look up the existing row BEFORE the update so we can record the
    # human-readable key_name (not the opaque cred_id) in the audit target.
    existing = _get_table(request).get(cred_id)
    if not existing:
        return JSONResponse({"error": "Not found"}, status_code=404)

    item = _get_table(request).update(cred_id, data)
    if not item:
        # Race: row was deleted between get() and update(). Treat as 404.
        return JSONResponse({"error": "Not found"}, status_code=404)

    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is not None:
        # Only populate after_val if key_value was actually updated.
        after_val = _redact(data["key_value"]) if "key_value" in data else None
        await audit_log.record(
            "credentials.put",
            actor="admin",
            target=existing["key_name"],
            before_val=None,
            after_val=after_val,
            source_ip=request.client.host if request.client else None,
        )
    return {"ok": True}
```

**Modify `delete_credential`** — look up `key_name` BEFORE the delete:

```python
@router.delete("/{cred_id}")
async def delete_credential(cred_id: str, request: Request):
    existing = _get_table(request).get(cred_id)
    if not existing:
        return JSONResponse({"error": "Not found"}, status_code=404)

    if not _get_table(request).delete(cred_id):
        # Race: already gone.
        return JSONResponse({"error": "Not found"}, status_code=404)

    audit_log = getattr(request.app.state, "audit_log", None)
    if audit_log is not None:
        await audit_log.record(
            "credentials.delete",
            actor="admin",
            target=existing["key_name"],
            before_val=None,
            after_val=None,
            source_ip=request.client.host if request.client else None,
        )
    return {"ok": True}
```

- [ ] Run the tests again — expect 6 passed:

```bash
uv run pytest tests/integration/test_audit_hooks.py::TestCredentialsHooks -v
```

- [ ] Run the full `test_audit_hooks.py` file to confirm no regressions in the other audit hook tests:

```bash
uv run pytest tests/integration/test_audit_hooks.py -v
```

Expected: all tests pass (including the existing `TestLoginHooks`, `TestSettingsHook`, `TestSessionDeleteHook`, `TestInternalHooks`).

### Step 1.3: Update the dashboard Audit page to show new actions

- [ ] The Audit page at `src/raisebull/admin/static/pages/audit.js` has a `categories` array with checkbox groups. The `Dashboard` group currently has `settings.put` and `session.delete`. Add the three new credential actions.

Find this block:
```javascript
categories: [
  { name: 'Auth',      actions: ['login.success', 'login.fail'] },
  { name: 'Dashboard', actions: ['settings.put', 'session.delete'] },
  { name: 'Internal',  actions: ['internal.heartbeat', 'internal.nightly_compact', 'internal.discord_push'] },
  { name: 'Scheduler', actions: ['scheduler.heartbeat', 'scheduler.nightly_compact', 'scheduler.discord_push'] },
  { name: 'LINE',      actions: ['line.signature_fail'] },
],
```

Update the `Dashboard` line to include the three new actions:
```javascript
  { name: 'Dashboard', actions: ['settings.put', 'session.delete', 'credentials.create', 'credentials.put', 'credentials.delete'] },
```

Also add the three new actions to the default-checked `selectedActions` Set:
```javascript
selectedActions: new Set([
  'login.success', 'login.fail',
  'settings.put', 'session.delete',
  'credentials.create', 'credentials.put', 'credentials.delete',  // NEW
  'internal.heartbeat', 'internal.nightly_compact', 'internal.discord_push',
  'scheduler.heartbeat', 'scheduler.nightly_compact', 'scheduler.discord_push',
  'line.signature_fail',
]),
```

No new tests needed for the JS change — the existing Playwright tests cover the filter UI structure.

### Step 1.4: Commit N1

- [ ] Stage and commit:

```bash
git add src/raisebull/admin/routes_credentials.py \
        src/raisebull/admin/static/pages/audit.js \
        tests/integration/test_audit_hooks.py
git commit -m "$(cat <<'EOF'
feat(audit): hook credentials create/put/delete with redaction

Closes the biggest security forensics gap in the audit log feature:
credential mutations were completely invisible. Adds three new actions:

- credentials.create — when a new row is added via POST /api/credentials
- credentials.put — when an existing row is updated via PUT /api/credentials/{id}
- credentials.delete — when a row is removed via DELETE /api/credentials/{id}

Redaction rule: after_val = "***<last 4 chars>" for create and for put
when key_value changed. before_val is ALWAYS NULL — logging the old
value would leak the previous credential to anyone who can read the
audit log. For put with only service changed (no key_value), after_val
is NULL so forensics can still see "this credential's metadata was
touched" without any secret content.

target is the human-readable key_name (looked up from the DB before
delete/update) rather than the opaque cred_id.

404 branches of put/delete return early BEFORE the hook, so failed
lookups produce zero audit rows.

POST /api/credentials/test is NOT audited — it's read-only and
receives raw key_value, which would leak if audited carelessly.

Dashboard audit page updated: Dashboard category group now has 5
checkboxes (settings.put, session.delete, credentials.create,
credentials.put, credentials.delete), all default-checked.

6 new tests in TestCredentialsHooks — including a regression guard
that scans EVERY audit row field for a unique sentinel string after
create+update+delete round-trip, proving the full value never leaks.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 (N2): Fix `nightly_compact_threshold round-trips` e2e flake

**Files:**
- Modify: `tests/e2e/dashboard.spec.ts` (the specific test at line ~120)

### Context

This e2e test was failing on main **BEFORE** feat/audit-logs started — confirmed by the final verification pass of the audit log work (documented in `docs/future-improvements.md` item 11). The pre-push hook currently lets it through because we know it's broken, but every push run shows `1 failed` which creates alert fatigue.

### Step 2.1: Reproduce locally

- [ ] Make sure no stale uvicorn is bound to port 8766:

```bash
lsof -ti:8766 | xargs kill 2>/dev/null || true
```

- [ ] Run JUST the failing test with `--headed` and `--debug` if possible to see what's happening:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
SKIP_LLM_E2E=1 npx playwright test --grep "nightly_compact_threshold round-trips" --reporter=list
```

Expected: 1 failure. Capture the full error output — what does Playwright say it saw vs expected?

- [ ] Examine the test body at `tests/e2e/dashboard.spec.ts:120` — read lines ~110-155 to understand the assertion:

```bash
sed -n '115,160p' tests/e2e/dashboard.spec.ts
```

### Step 2.2: Diagnose the root cause

Three common failure modes for a "round-trips through save button" test:

1. **Timing issue** — toast / form re-render happens AFTER the assertion reads the DOM. Fix: add explicit `await expect(page.locator(...)).toHaveValue(...)` with Playwright's auto-retry instead of `page.inputValue()` + bare equality.

2. **Locator ambiguity / strict mode violation** — the test finds MORE than one matching element. Fix: use a more specific selector (id, data-testid, `.first()` as last resort).

3. **Real backend bug** — the save button actually isn't persisting the value, or the GET after save returns a different value. Fix: inspect the backend PUT/GET flow for the specific key.

Look at the Playwright error output to determine which category. If it says "expected X got Y", it's probably 3. If it says "locator resolved to N elements", it's 2. If it says "timeout waiting for...", it's 1.

- [ ] Open `tests/e2e/dashboard.spec.ts` and study the failing test's body. Look at what selectors it uses, what values it sets, what assertions it makes, and in what order.

- [ ] If a trace file was generated, open it:
```bash
npx playwright show-trace test-results/*/trace.zip
```

### Step 2.3: Apply the minimal fix

The fix depends on what you find. Do NOT expand scope — fix only this specific test. Possibilities:

- **Timing**: convert `await page.inputValue('...')` to `await expect(page.locator('...')).toHaveValue(...)`.
- **Locator**: prepend `data-testid` to the affected input, update the test to use it. Only add `data-testid` if it's missing and replacement is safer.
- **Backend bug**: follow the bug to `src/raisebull/admin/routes_settings.py` and fix the round-trip. This is the scariest branch — if you end up here, the scope has grown beyond "fix flake", and you should pause to consider whether this warrants its own branch.

### Step 2.4: Verify the fix

- [ ] Re-run JUST the failing test until it passes 3 times in a row (catches flake that's not fully fixed):

```bash
for i in 1 2 3; do
  echo "=== Run $i ==="
  SKIP_LLM_E2E=1 npx playwright test --grep "nightly_compact_threshold round-trips" --reporter=list || break
done
```

Expected: 3 consecutive passes.

- [ ] Run the full LLM-free e2e subset to confirm no collateral damage:

```bash
SKIP_LLM_E2E=1 npx playwright test --reporter=list 2>&1 | tail -30
```

Expected: 21 passed (was 20 passed + 1 failed before the fix).

### Step 2.5: Commit N2

- [ ] Commit with a message that documents WHAT the root cause was so future archaeology is easier:

```bash
git add tests/e2e/dashboard.spec.ts  # plus any source file you had to touch
git commit -m "$(cat <<'EOF'
fix(e2e): repair nightly_compact_threshold round-trips flake

Root cause: <fill this in with what you actually found>

Fix: <fill this in with what you actually changed>

Pre-existing failure on main since before feat/audit-logs — documented
as item 11 in docs/future-improvements.md. Every push previously
showed "1 failed" in the pre-push hook output which created alert
fatigue. Now 21/21 LLM-free e2e tests pass.

Verified by running the specific test 3 times in a row without
failure.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 (N3): `_normalize_iso` symmetry cleanup

**Files:**
- Modify: `src/raisebull/admin/routes_audit.py` (delete `_normalize_iso` + its callsites)
- Modify: `src/raisebull/admin/static/pages/audit.js` (send `+00:00` instead of `Z`)
- Modify: `tests/integration/test_audit_api.py` (delete `test_list_audit_accepts_z_suffix`)

### Context

`AuditLog.record()` stores timestamps as `datetime.now(timezone.utc).isoformat()` which produces `2026-04-08T03:42:11.123456+00:00`. The dashboard frontend `audit.js` sends `from=2026-04-08T00:00:00Z` (JavaScript's `Date.toISOString()` format). These two formats represent the same moment but **sort differently as TEXT** because `Z` (ASCII 90) > `+` (ASCII 43). Without normalization, a Z-suffix query would miss boundary rows.

The current fix is `_normalize_iso()` in `routes_audit.py` which rewrites `Z` → `+00:00` at the API boundary. It only handles `Z`, not arbitrary offsets like `+08:00`.

**Cleaner approach (Option A — chosen):** have the frontend send `+00:00` directly. Backend stores `+00:00`. Frontend sends `+00:00`. Same format throughout. Delete the helper. No more asymmetry.

### Step 3.1: Delete `_normalize_iso` from routes_audit.py

- [ ] Open `src/raisebull/admin/routes_audit.py`. Delete the `_normalize_iso` function entirely. Also delete the docstring comment if it's adjacent.

- [ ] Find the two callsites in the `list_audit` handler:

```python
rows = await audit_log.list_recent(
    from_ts=_normalize_iso(from_ts),
    to_ts=_normalize_iso(to_ts),
    limit=limit + 1,
)
```

Replace with:
```python
rows = await audit_log.list_recent(
    from_ts=from_ts,
    to_ts=to_ts,
    limit=limit + 1,
)
```

### Step 3.2: Update audit.js to send `+00:00`

- [ ] Open `src/raisebull/admin/static/pages/audit.js`. Find the `load()` method:

```javascript
async load() {
  this.loading = true;
  this.error = null;
  try {
    const from = `${this.fromDate}T00:00:00Z`;
    const to = `${this.toDate}T23:59:59Z`;
    // ...
```

Change the `from`/`to` format:

```javascript
    const from = `${this.fromDate}T00:00:00+00:00`;
    const to = `${this.toDate}T23:59:59+00:00`;
```

**Note the `+` character**: when passed to `fetch()` with query string interpolation, `+` is a URL-encoding pitfall — it can be interpreted as a space. The existing code already uses `encodeURIComponent()`:

```javascript
const res = await fetch(
  `/admin/api/audit?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=500`
);
```

`encodeURIComponent('2026-04-08T00:00:00+00:00')` produces `2026-04-08T00%3A00%3A00%2B00%3A00` which the FastAPI query parser decodes back to `2026-04-08T00:00:00+00:00` correctly. **Do not remove `encodeURIComponent` or this will break.** Verify by grep that it's still there.

### Step 3.3: Delete the obsolete Z-suffix test

- [ ] Open `tests/integration/test_audit_api.py`. Find and delete the `test_list_audit_accepts_z_suffix` method. The other 4 tests in that file (`test_list_audit_requires_auth`, `test_list_audit_returns_rows_desc`, `test_list_audit_date_range_filter`, `test_list_audit_truncated_flag`) already cover the `+00:00` format implicitly, so removing this test reduces coverage of "Z support" (which we're explicitly dropping) without touching the canonical-format coverage.

### Step 3.4: Run affected tests

- [ ] Run the audit API tests:

```bash
uv run pytest tests/integration/test_audit_api.py -v
```

Expected: 4 passed (was 5).

- [ ] Run the audit hooks tests to confirm N1 didn't regress:

```bash
uv run pytest tests/integration/test_audit_hooks.py -v
```

Expected: all tests pass.

- [ ] Run the audit e2e tests — these exercise the actual frontend → backend flow with the new `+00:00` format:

```bash
SKIP_LLM_E2E=1 npx playwright test tests/e2e/audit.spec.ts --reporter=list
```

Expected: 2 passed.

### Step 3.5: Commit N3

- [ ] Commit:

```bash
git add src/raisebull/admin/routes_audit.py \
        src/raisebull/admin/static/pages/audit.js \
        tests/integration/test_audit_api.py
git commit -m "$(cat <<'EOF'
refactor(audit): drop _normalize_iso helper, canonicalize on +00:00

Frontend audit.js now sends ISO strings with +00:00 suffix directly
instead of Z. Backend AuditLog stores timestamps as +00:00 via
datetime.isoformat(). Both sides now use the same canonical format,
eliminating the boundary asymmetry that forced _normalize_iso() to
exist.

- Deleted _normalize_iso() from routes_audit.py
- audit.js load() builds 'T00:00:00+00:00' / 'T23:59:59+00:00'
- Dropped test_list_audit_accepts_z_suffix (the behavior it tested is
  gone by design)

encodeURIComponent() is still in place so the '+' character in the URL
query string is properly escaped as %2B and decoded back correctly by
FastAPI's query parser.

Net code reduction: ~20 lines deleted, 0 lines added (other than the
updated frontend string).

If a third-party client ever needs to send Z suffix, they can be
routed through a new normalization layer at that point — YAGNI for
today.

Tech debt source: docs/future-improvements.md items 9c and 9d.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Final verification + push

**Files:** none

- [ ] Run the full fast suite to confirm N1+N2+N3 combined didn't break anything:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
uv run pytest tests/unit tests/integration tests/test_main.py tests/test_session.py tests/test_recovery.py tests/test_runner.py tests/test_discord_bot.py tests/test_audit_scheduler.py -q
```

Expected: 379 + 6 = **385 passed** (baseline 379 + 6 new `TestCredentialsHooks` tests).

- [ ] Run the LLM-free Playwright suite:

```bash
SKIP_LLM_E2E=1 npx playwright test --reporter=list 2>&1 | tail -10
```

Expected: **21 passed** (was 20 passed + 1 failed; N2 fixed the failing one).

- [ ] Push the branch (pre-push hook will re-run the fast suite + e2e):

```bash
git push -u origin feat/audit-log-follow-ups
```

- [ ] After successful push, fast-forward merge to main (after user approval):

```bash
git checkout main
git pull --ff-only origin main
git merge --ff-only feat/audit-log-follow-ups
git push origin main
```

- [ ] Optional but recommended: rebuild bull-daniu on samantha-wsl so production picks up the new credentials hook:

```bash
ssh -p 2222 samantha-machine@samantha-wsl.tail5a1118.ts.net \
  'cd ~/Github/raise-a-bull && git pull origin main && cd ~/docker/bot-daniu && docker compose up -d --build'
```

Smoke test: log into the production dashboard, touch a credential, then query `/admin/api/audit?action=credentials.put` (well, via the dashboard's date filter) to confirm the hook fires in prod.

---

## Spec Coverage Checklist

Do a fresh pass over this plan before submitting for review:

- **N1 spec** (`docs/future-improvements.md` item 7d "Credentials PUT hook with redaction") — covered by Task 1. Note that N1 was originally scoped as just PUT but this plan expands it to all 3 mutation endpoints (create/put/delete). This is the right call — they live in the same file and have the same forensics pattern. If the reviewer objects, the `credentials.create` and `credentials.delete` hooks can be split into a follow-up commit within the same branch.
- **N2 spec** (`docs/future-improvements.md` item 11 "Settings page nightly_compact_threshold round-trips e2e flaky on main") — covered by Task 2, but the actual fix is unknown until reproduction. Budget a full half-session since "unknown bug" tasks can blow up.
- **N3 spec** (`docs/future-improvements.md` items 9c + 9d — "Z vs +00:00 ISO format normalization only handles Z" + "Frontend and backend ISO format asymmetry") — covered by Task 3, using Option A (delete the helper, make frontend canonical). Option B (extend the helper with `datetime.fromisoformat()`) is explicitly rejected — we can always add it back later under YAGNI if a third-party client needs it.

## Open questions for the implementer

- **N1 tests reference `_redact` indirectly** (via `***mnop` string). If `_redact` is ever extracted into a separate testable helper, add a unit test for the `< 4 chars` edge case in `test_audit.py`. Low priority.
- **N2 root cause is unknown.** If diagnosis reveals a backend bug (not a test bug), consider whether it should be a separate branch. The plan's Task 2.3 flags this.
- **N3 encodeURIComponent behavior**: double-check by manually hitting the endpoint with a real `+` character before committing. `curl -G --data-urlencode 'from=2026-04-08T00:00:00+00:00' http://localhost:...` is a reliable way to verify.

---

## Reference: the existing audit log base

If you need to understand any of the existing hooks, here are the files that already have audit instrumentation from `feat/audit-logs`:

- `src/raisebull/admin/auth.py` — `login.success` / `login.fail` (the password-never-logged pattern)
- `src/raisebull/admin/routes_settings.py` — `settings.put` (the per-key diff pattern)
- `src/raisebull/admin/routes_chat.py` — `session.delete` (the 404-guard-before-hook pattern)
- `src/raisebull/main.py` — `/internal/*` triggers + `line.signature_fail` + `_heartbeat_push_impl`
- `src/raisebull/heartbeat.py` — `scheduler.heartbeat` (inside `_heartbeat_tick`, not `run_event_check`) + `scheduler.nightly_compact` (inside `_nightly_lock`)

The `AuditLog` class itself is at `src/raisebull/audit.py`. Do not modify it — this plan only adds new actions via `record()` calls.
