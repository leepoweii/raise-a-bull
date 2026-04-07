# Nightly Compact Config + Trigger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the nightly-compact token threshold runtime-configurable via dashboard, add a manual trigger endpoint for testing, and lock both internal trigger endpoints to localhost-only callers.

**Architecture:** The 50K-token threshold currently lives as a module constant in `heartbeat.py`, so there's no way to test the compact path without pumping a real session past 50K. Add a `_read_threshold()` helper that resolves precedence `settings.json > NIGHTLY_COMPACT_THRESHOLD env > hardcoded 50000`, with `0/negative/non-numeric` falling back to default. Wire it into `nightly_compact()` so each cron tick re-reads the latest value (no restart needed when user changes it on the dashboard). Add a new `POST /internal/nightly-compact/trigger` endpoint mirroring the existing `/internal/heartbeat/trigger`, and gate both behind a shared `_require_localhost()` helper that checks `request.client.host` against `127.0.0.1`/`::1`. Smoke test seeds two sessions (one above threshold, one below) and runs `nightly_compact()` once to verify the eligible session is compacted while the ineligible one is untouched.

**Tech Stack:** Python 3.12, FastAPI, pytest + pytest-asyncio, httpx (smoke), aiosqlite, real Claude CLI subprocess (smoke).

**Branch:** Continue on `feature/session-management` (already checked out).

---

## Changelog

**v2 (2026-04-07, post-review):** Patches applied after Opus + Sonnet + Haiku review:
- 🔴 **Task 3 lock** — Added module-level `asyncio.Lock` so cron + manual trigger can't race. APScheduler `max_instances=1` only protects the same job_id; manual trigger via `asyncio.create_task()` bypasses it entirely. Without the lock, two concurrent `nightly_compact()` runs would double-call `/compact` on the same session_id and race `update_compacted_at()`. Split Task 3 into two commits (threshold + lock) to keep diffs focused.
- 🔴 **Task 4 PUT validation** — Reject `nightly_compact_threshold` PUT with non-positive int (400). Without this, `_read_settings()` (no validation) and `_read_threshold()` (validates) diverge: dashboard shows `"abc"` but `nightly_compact()` silently uses 50000.
- 🟡 **Task 3 RED expectation** — Original expected text was wrong. With hardcoded 50000 threshold and seeded tokens 2000/500, the failure mode is "neither session compacted; assertion `above["session_id"] == "new-above-sid"` fails". Corrected.
- 🟡 **Task 6 timeout** — Bumped `MAX_WAIT_SECONDS` from 240 to 600. Two real Claude calls can exceed 240s on a slow run.
- 🟡 **Task 5 doc note** — Documented that the localhost gate is intentional for `/internal/*` and that any future "Run nightly compact now" dashboard button must use the admin auth cookie session, not bypass the IP gate.
- 🟢 **Task 2 +1 test** — Added `test_zero_in_env_falls_back_to_default` (env var case).
- 🟢 **Task 5 IPv6 test** — Added `ok=True` body assertion alongside the 200 status check.

httpx version verified as `>=0.27` (locked at 0.28.1) — `ASGITransport(client=...)` is supported.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/raisebull/heartbeat.py` | `_read_threshold()` helper, `is_compact_eligible(threshold=...)` param, `nightly_compact()` reads dynamic threshold | Modify |
| `src/raisebull/admin/routes_settings.py` | `_ALLOWED_KEYS` includes `nightly_compact_threshold` | Modify (1 line) |
| `src/raisebull/main.py` | `_require_localhost()` helper, new `/internal/nightly-compact/trigger`, apply gate to `/internal/heartbeat/trigger` | Modify |
| `tests/unit/test_nightly_compact.py` | Threshold parameter + `_read_threshold()` precedence tests | Modify |
| `tests/integration/test_admin.py` | Settings expected_keys + put round-trip for new key | Modify |
| `tests/test_main.py` | Trigger endpoint + localhost gate tests | Modify |
| `tests/smoke/test_nightly_compact_live.py` | End-to-end smoke: two-session above/below threshold | Create |

**Why split this way:** Each file owns one concern. Threshold logic stays inside `heartbeat.py` because it's a heartbeat-domain concept. The settings registry only needs a single key entry. Endpoint plumbing stays in `main.py` next to its sibling. Tests mirror the layout — unit for pure functions, integration for HTTP/DB, smoke for end-to-end real-LLM.

---

## Background Context (read this before starting)

**The current `nightly_compact()` flow** (`src/raisebull/heartbeat.py:125-180`):
1. List all sessions via `sessions.list_all()`
2. Filter eligible: `token_count > 50000` AND new activity since last compact AND not a `heartbeat:*` session
3. For each eligible session: optionally inject buffered messages, run `/compact`, save new session_id, stamp `last_compacted_at` AFTER save (so `last_compacted_at >= last_active`)
4. Run a single consolidate prompt (no session_id) to update memory files

**Key invariants you must NOT break:**
- `last_compacted_at` is captured via `datetime.now(timezone.utc).isoformat()` AFTER `sessions.save()` finishes — this prevents `is_compact_eligible()` from re-treating the compact itself as new activity (re-compact loop fix from commit `d0b8642`)
- Buffer is only deleted when `inject_result.error is None` — if injection fails, the buffer is preserved for next run
- `heartbeat:*` sessions are always skipped (no point compacting throwaway heartbeat history)
- `is_compact_eligible()` uses strict `>` not `>=` against the threshold

**Existing tests that will need to be adjusted:**
- `tests/unit/test_nightly_compact.py::TestCompactEligibility::test_threshold_boundary` — uses 50000 boundary, must still work after threshold becomes a parameter
- `tests/integration/test_admin.py::TestSettings::test_get_settings_defaults` line 212 — uses `expected_keys` set, must add the new key
- `tests/test_main.py::test_heartbeat_trigger_returns_ok` — calls `/internal/heartbeat/trigger` without setting client host, will need a header or test client config to satisfy localhost check

**ASGI client host gotcha:** httpx's `AsyncClient(transport=ASGITransport(app=app))` does NOT populate `request.client` by default — `request.client` is `None`. The `_require_localhost()` helper must handle `client is None` as **localhost** (because TestClient/ASGITransport simulate same-process calls), otherwise tests will all return 403. In a real HTTP server (uvicorn), `request.client.host` is always populated.

**Settings precedence semantics** (already established by `_read_settings()` in `routes_settings.py:32`):
- Default value first
- Env var override second (only if non-empty after strip)
- JSON file override third (highest precedence)

`_read_threshold()` MUST follow this same order so dashboard edits beat env vars beat hardcoded defaults.

---

## Task 1: Threshold parameter on `is_compact_eligible()`

**Files:**
- Modify: `src/raisebull/heartbeat.py:30-39`
- Test: `tests/unit/test_nightly_compact.py:8-39`

**Goal:** Make `is_compact_eligible()` accept a `threshold` keyword argument (default 50000 for backward compatibility). Existing call sites and tests should be unaffected.

- [ ] **Step 1: Write the failing tests**

Append these tests inside `class TestCompactEligibility` in `tests/unit/test_nightly_compact.py`:

```python
    def test_eligible_with_custom_threshold_below_token_count(self):
        session = {
            "token_count": 3000,
            "last_compacted_at": None,
            "last_active": "2026-04-07T10:00:00",
        }
        assert is_compact_eligible(session, threshold=2000) is True

    def test_not_eligible_with_custom_threshold_above_token_count(self):
        session = {
            "token_count": 1500,
            "last_compacted_at": None,
            "last_active": "2026-04-07T10:00:00",
        }
        assert is_compact_eligible(session, threshold=2000) is False

    def test_custom_threshold_uses_strict_greater_than(self):
        session = {
            "token_count": 2000,
            "last_compacted_at": None,
            "last_active": "2026-04-07T10:00:00",
        }
        assert is_compact_eligible(session, threshold=2000) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestCompactEligibility -v`
Expected: 3 NEW tests FAIL with `TypeError: is_compact_eligible() got an unexpected keyword argument 'threshold'`

- [ ] **Step 3: Add the threshold parameter**

In `src/raisebull/heartbeat.py`, replace the existing `is_compact_eligible` function (lines 30-39) with:

```python
def is_compact_eligible(
    session: dict,
    key: str = "",
    threshold: int = COMPACT_TOKEN_THRESHOLD,
) -> bool:
    """Check if a session should be compacted in the nightly job."""
    if key.startswith("heartbeat:"):
        return False
    if session["token_count"] <= threshold:
        return False
    last_compacted = session.get("last_compacted_at")
    if last_compacted and session["last_active"] <= last_compacted:
        return False  # No new activity since last compact
    return True
```

- [ ] **Step 4: Run all eligibility tests to verify pass**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestCompactEligibility -v`
Expected: 9 passed (6 existing + 3 new)

- [ ] **Step 5: Run full unit test suite to confirm nothing else broke**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/ -q`
Expected: all unit tests still pass (no count regression vs pre-change baseline)

- [ ] **Step 6: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add src/raisebull/heartbeat.py tests/unit/test_nightly_compact.py
git commit -m "$(cat <<'EOF'
feat: is_compact_eligible accepts threshold parameter

Step 1 of making nightly-compact threshold runtime-configurable. The
function now accepts an optional threshold kwarg (default 50000 preserves
existing behavior). Pure-function refactor — no caller changes yet.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `_read_threshold()` helper with full precedence

**Files:**
- Modify: `src/raisebull/heartbeat.py` (add helper near `is_compact_eligible`)
- Test: `tests/unit/test_nightly_compact.py` (new `TestReadThreshold` class)

**Goal:** Resolve threshold precedence settings.json → env → 50000, with bad inputs falling back to 50000.

- [ ] **Step 1: Write the failing tests**

Add this new test class to `tests/unit/test_nightly_compact.py` (after the existing `TestCompactEligibility` class):

```python
class TestReadThreshold:
    def test_default_when_no_settings_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_env_overrides_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "12345")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 12345

    def test_settings_json_overrides_env(self, tmp_path, monkeypatch):
        import json
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "12345")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "9999"})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 9999

    def test_settings_int_value_works(self, tmp_path, monkeypatch):
        import json
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": 7777})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 7777

    def test_zero_in_settings_falls_back_to_default(self, tmp_path, monkeypatch):
        import json
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "0"})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_negative_in_settings_falls_back_to_default(self, tmp_path, monkeypatch):
        import json
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "-100"})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_garbage_in_settings_falls_back_to_env(self, tmp_path, monkeypatch):
        import json
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "8888")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "abc"})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 8888

    def test_garbage_env_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "not-a-number")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_zero_in_env_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "0")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_negative_in_env_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "-50")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_corrupted_settings_json_falls_back_to_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "6666")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text("{ not valid json")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 6666

    def test_missing_workspace_directory_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        nonexistent = tmp_path / "does-not-exist"
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(nonexistent)) == 50000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestReadThreshold -v`
Expected: 12 tests FAIL with `ImportError: cannot import name '_read_threshold' from 'raisebull.heartbeat'`

- [ ] **Step 3: Implement `_read_threshold()`**

Add these imports at the top of `src/raisebull/heartbeat.py` if they aren't already present (verify with `grep '^import\|^from' src/raisebull/heartbeat.py`):

```python
import json
from pathlib import Path
```

(`import json` and `from pathlib import Path` may need to be added — the existing file already has `import os`, `import re`, `import logging` at the top.)

Then add this helper function in `src/raisebull/heartbeat.py`, immediately after the `is_compact_eligible` function:

```python
def _coerce_threshold(value) -> int | None:
    """Convert raw value to a positive int, or return None if invalid/non-positive."""
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None
    if n <= 0:
        return None
    return n


def _read_threshold(workspace: str) -> int:
    """Resolve nightly-compact threshold.

    Precedence: settings.json > NIGHTLY_COMPACT_THRESHOLD env > 50000.
    Invalid (non-numeric, zero, negative) values fall through to the next layer.
    """
    settings_path = Path(workspace) / "config" / "settings.json"
    if settings_path.exists():
        try:
            stored = json.loads(settings_path.read_text(encoding="utf-8"))
            from_settings = _coerce_threshold(stored.get("nightly_compact_threshold"))
            if from_settings is not None:
                return from_settings
        except (json.JSONDecodeError, OSError):
            pass

    from_env = _coerce_threshold(os.environ.get("NIGHTLY_COMPACT_THRESHOLD"))
    if from_env is not None:
        return from_env

    return COMPACT_TOKEN_THRESHOLD
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestReadThreshold -v`
Expected: 12 passed

- [ ] **Step 5: Run full unit test suite**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/ -q`
Expected: all unit tests pass

- [ ] **Step 6: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add src/raisebull/heartbeat.py tests/unit/test_nightly_compact.py
git commit -m "$(cat <<'EOF'
feat: _read_threshold helper with settings/env/default precedence

Resolves nightly-compact token threshold from settings.json (highest),
NIGHTLY_COMPACT_THRESHOLD env, or hardcoded 50000 default. Invalid values
(non-numeric, zero, negative) fall through to the next layer rather than
silently disabling compact.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `nightly_compact()` uses dynamic threshold

**Files:**
- Modify: `src/raisebull/heartbeat.py:125-180` (the `nightly_compact` function)
- Test: `tests/unit/test_nightly_compact.py` (new `TestNightlyCompactThreshold` class)

**Goal:** `nightly_compact()` reads the current threshold at the start of each invocation (so dashboard changes take effect on the next cron tick without restart) and only the eligible sessions get processed.

- [ ] **Step 1: Write the failing test**

Add this test class at the bottom of `tests/unit/test_nightly_compact.py`:

```python
class TestNightlyCompactThreshold:
    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_nightly_compact_uses_threshold_from_settings(
        self, store, tmp_path, monkeypatch
    ):
        """nightly_compact reads threshold from workspace/config/settings.json."""
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        # Seed sessions: one above custom threshold (1000), one below
        await store.save("web:above", session_id="orig-above", domain="web", token_count=2000)
        await store.save("web:below", session_id="orig-below", domain="web", token_count=500)

        # Write settings.json with low threshold so "above" becomes eligible
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        # Mock runner: /compact returns a new session id, consolidate is no-op
        runner = MagicMock()
        runner.workspace = str(workspace)
        compact_result = MagicMock(error=None, session_id="new-above-sid", output_tokens=900)
        consolidate_result = MagicMock(error=None, session_id=None, output_tokens=10)
        runner.run = AsyncMock(side_effect=[compact_result, consolidate_result])

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)

        await nightly_compact(runner, store, buffer=None)

        # "above" was compacted: new session_id, token_count updated
        above = await store.get("web:above")
        assert above["session_id"] == "new-above-sid"
        assert above["last_compacted_at"] is not None

        # "below" untouched
        below = await store.get("web:below")
        assert below["session_id"] == "orig-below"
        assert below["last_compacted_at"] is None
        assert below["token_count"] == 500

        # runner.run called exactly twice: once for /compact, once for consolidate
        assert runner.run.call_count == 2
        first_call_prompt = runner.run.call_args_list[0].args[0]
        assert first_call_prompt == "/compact"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestNightlyCompactThreshold -v`
Expected: FAIL — `nightly_compact()` still uses hardcoded `COMPACT_TOKEN_THRESHOLD = 50_000`, so neither seeded session (5000 / 500 tokens) qualifies. `is_compact_eligible()` returns `False` for both, the eligible list is empty, `runner.run` is never called, and the assertion `above["session_id"] == "new-above-sid"` fails because the session is unchanged (`session_id` is still `"orig-above"`). This is the correct RED — the test will go GREEN once Step 3 wires `_read_threshold()` in so the function picks up the 1000-token threshold from `settings.json`.

- [ ] **Step 3: Wire `_read_threshold()` into `nightly_compact()`**

In `src/raisebull/heartbeat.py`, modify the `nightly_compact` function. Replace the existing function (currently at lines 125-180) with this version. The two changes are: (1) add `threshold = _read_threshold(...)` near the top, (2) pass `threshold=threshold` into the `is_compact_eligible` call:

```python
async def nightly_compact(runner: ClaudeRunner, sessions: SessionStore, buffer=None) -> None:
    """Run nightly compact + consolidate. Called by scheduler at configured hour."""
    from datetime import timezone

    threshold = _read_threshold(runner.workspace or "/app/workspace")

    all_sessions = await sessions.list_all()
    eligible = [
        s for s in all_sessions
        if is_compact_eligible(s, key=s["key"], threshold=threshold)
    ]

    if not eligible:
        logger.info("Nightly compact: no eligible sessions (threshold=%d)", threshold)
        return

    for s in eligible:
        key = s["key"]
        session_id = s["session_id"]
        logger.info("Nightly compact: %s (tokens=%d, threshold=%d)", key, s["token_count"], threshold)

        # Step 1: inject unprocessed buffer into session
        if buffer:
            msgs = await buffer.get_all(key)
            if msgs:
                prompt = await buffer.build_prompt(key, "(nightly compact — injecting buffered messages)")
                inject_result = await runner.run(prompt, session_id=session_id, timeout_seconds=300.0)
                if not inject_result.error:
                    # Only clear buffer once we know the injection succeeded
                    await buffer.delete_channel(key)
                    session_id = inject_result.session_id or session_id
                else:
                    logger.warning("Buffer injection failed for %s, keeping buffer: %s", key, inject_result.error)

        # Step 2: compact
        result = await runner.run("/compact", session_id=session_id, timeout_seconds=300.0)
        if result.error:
            logger.error("Compact failed for %s: %s", key, result.error)
            continue

        # Step 3: update DB — save new session_id, then stamp last_compacted_at >= last_active
        new_session_id = result.session_id or session_id
        await sessions.save(
            key, session_id=new_session_id, domain=s["domain"],
            token_count=result.output_tokens or s["token_count"],
        )
        # Capture timestamp AFTER save() so last_compacted_at >= last_active,
        # preventing is_compact_eligible() from treating the compact itself as new activity.
        now = datetime.now(timezone.utc).isoformat()
        await sessions.update_compacted_at(key, now)

    # Step 4: consolidate — one LLM call to update memory
    summary_parts = [f"Session {s['key']}: {s['token_count']} tokens" for s in eligible]
    consolidate_prompt = (
        "你是記憶整理助理。以下 session 剛剛被 compact 了。\n"
        "請讀取各 session 的最新狀態，整理重要資訊，更新 memory/ 目錄下的相關檔案。\n"
        "你可以自行決定要寫入哪些檔案。\n\n"
        + "\n".join(summary_parts)
    )
    await runner.run(consolidate_prompt, session_id=None, timeout_seconds=600.0)
    logger.info("Nightly consolidate complete")
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestNightlyCompactThreshold -v`
Expected: 1 passed

- [ ] **Step 5: Run full unit test suite**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/ -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add src/raisebull/heartbeat.py tests/unit/test_nightly_compact.py
git commit -m "$(cat <<'EOF'
feat: nightly_compact reads threshold dynamically

Each tick re-reads the threshold via _read_threshold() so dashboard
changes take effect on the next cron run without restart. Logs the
threshold alongside the eligibility decision for easier ops debugging.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 3b: Concurrent run protection (asyncio.Lock)

**Why this lives inside Task 3:** Task 3 just wired `nightly_compact()` to be invokable from anywhere (cron + soon-to-be-added manual trigger in Task 5). APScheduler's `max_instances=1` only protects the same `job_id` from concurrent execution — it has zero effect on `asyncio.create_task(nightly_compact(...))` calls coming from a trigger endpoint. Without a lock, a manual trigger fired while the 03:00 cron is mid-flight would run a second `nightly_compact()` concurrently on the same sessions, double-calling `/compact` and racing `update_compacted_at()`. Add the lock now, before the trigger endpoint exists in Task 5.

**Files:**
- Modify: `src/raisebull/heartbeat.py` (add module-level lock + wrap `nightly_compact()` body)
- Test: `tests/unit/test_nightly_compact.py` (extend `TestNightlyCompactThreshold`)

- [ ] **Step 7: Write the failing concurrency test**

Append this test method to `class TestNightlyCompactThreshold` in `tests/unit/test_nightly_compact.py`:

```python
    @pytest.mark.asyncio
    async def test_concurrent_runs_serialize_via_lock(
        self, store, tmp_path, monkeypatch
    ):
        """Two concurrent nightly_compact calls must not double-compact a session.

        Without a lock: both runs see the session as eligible (token_count > threshold,
        last_compacted_at is None) and both call runner.run for /compact + consolidate
        → 4 runner.run calls total. With the lock: run 1 holds the lock, compacts the
        session, releases. Run 2 takes the lock, sees the session is no longer eligible
        (last_compacted_at is now set, last_active is unchanged), and exits early
        without calling runner.run → 2 total calls.
        """
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        await store.save("web:hot", session_id="orig", domain="web", token_count=5000)

        runner = MagicMock()
        runner.workspace = str(workspace)

        async def slow_run(*args, **kwargs):
            # Simulate a non-trivial Claude call so the two coroutines actually overlap
            # in time if they're not serialized.
            await asyncio.sleep(0.05)
            return MagicMock(error=None, session_id="new-sid", output_tokens=900)

        runner.run = AsyncMock(side_effect=slow_run)

        # Fire two concurrent nightly_compact runs
        await asyncio.gather(
            nightly_compact(runner, store, buffer=None),
            nightly_compact(runner, store, buffer=None),
        )

        # Run 1: 1× /compact + 1× consolidate = 2 runner.run calls.
        # Run 2: lock blocks until Run 1 finishes; then Run 2 sees the now-compacted
        # session as ineligible (last_compacted_at >= last_active) and exits before
        # calling runner.run at all.
        assert runner.run.call_count == 2, (
            f"Expected serialized execution (2 calls), got {runner.run.call_count}. "
            "Without the lock, both runs would each call /compact + consolidate = 4 calls."
        )

        # Sanity: the session was actually compacted exactly once
        row = await store.get("web:hot")
        assert row["session_id"] == "new-sid"
        assert row["last_compacted_at"] is not None
```

Also add `import asyncio` at the top of the test file if it's not already there (run `grep '^import asyncio' tests/unit/test_nightly_compact.py` to verify; if missing, add it after the `import pytest` line).

- [ ] **Step 8: Run the test to verify it fails**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestNightlyCompactThreshold::test_concurrent_runs_serialize_via_lock -v`
Expected: FAIL with `AssertionError: Expected serialized execution (2 calls), got 4`. Both concurrent runs see the session as eligible because there's no lock, so both call `runner.run` for compact + consolidate.

- [ ] **Step 9: Add the module-level lock and wrap nightly_compact body**

In `src/raisebull/heartbeat.py`, add a module-level lock declaration. Place it near the top of the file, after the existing module constants (the `HEARTBEAT_INTERVAL`, `MAX_DAILY_TRIGGERS`, `COMPACT_TOKEN_THRESHOLD` block):

```python
# Serializes nightly_compact across cron + manual trigger callers.
# APScheduler's max_instances=1 only protects the same job_id; the manual
# /internal/nightly-compact/trigger endpoint dispatches via asyncio.create_task,
# completely bypassing the scheduler. This module-level lock ensures cron and
# trigger paths can never run nightly_compact concurrently on the same DB.
_nightly_lock = asyncio.Lock()
```

Then wrap the entire body of `nightly_compact()` (everything after the `from datetime import timezone` import and before the function returns) inside `async with _nightly_lock:`. Replace the function body with:

```python
async def nightly_compact(runner: ClaudeRunner, sessions: SessionStore, buffer=None) -> None:
    """Run nightly compact + consolidate. Called by scheduler at configured hour.

    Serialized via _nightly_lock so concurrent invocations (cron + manual trigger)
    can't double-compact the same session.
    """
    from datetime import timezone

    async with _nightly_lock:
        threshold = _read_threshold(runner.workspace or "/app/workspace")

        all_sessions = await sessions.list_all()
        eligible = [
            s for s in all_sessions
            if is_compact_eligible(s, key=s["key"], threshold=threshold)
        ]

        if not eligible:
            logger.info("Nightly compact: no eligible sessions (threshold=%d)", threshold)
            return

        for s in eligible:
            key = s["key"]
            session_id = s["session_id"]
            logger.info("Nightly compact: %s (tokens=%d, threshold=%d)", key, s["token_count"], threshold)

            # Step 1: inject unprocessed buffer into session
            if buffer:
                msgs = await buffer.get_all(key)
                if msgs:
                    prompt = await buffer.build_prompt(key, "(nightly compact — injecting buffered messages)")
                    inject_result = await runner.run(prompt, session_id=session_id, timeout_seconds=300.0)
                    if not inject_result.error:
                        # Only clear buffer once we know the injection succeeded
                        await buffer.delete_channel(key)
                        session_id = inject_result.session_id or session_id
                    else:
                        logger.warning("Buffer injection failed for %s, keeping buffer: %s", key, inject_result.error)

            # Step 2: compact
            result = await runner.run("/compact", session_id=session_id, timeout_seconds=300.0)
            if result.error:
                logger.error("Compact failed for %s: %s", key, result.error)
                continue

            # Step 3: update DB — save new session_id, then stamp last_compacted_at >= last_active
            new_session_id = result.session_id or session_id
            await sessions.save(
                key, session_id=new_session_id, domain=s["domain"],
                token_count=result.output_tokens or s["token_count"],
            )
            # Capture timestamp AFTER save() so last_compacted_at >= last_active,
            # preventing is_compact_eligible() from treating the compact itself as new activity.
            now = datetime.now(timezone.utc).isoformat()
            await sessions.update_compacted_at(key, now)

        # Step 4: consolidate — one LLM call to update memory
        summary_parts = [f"Session {s['key']}: {s['token_count']} tokens" for s in eligible]
        consolidate_prompt = (
            "你是記憶整理助理。以下 session 剛剛被 compact 了。\n"
            "請讀取各 session 的最新狀態，整理重要資訊，更新 memory/ 目錄下的相關檔案。\n"
            "你可以自行決定要寫入哪些檔案。\n\n"
            + "\n".join(summary_parts)
        )
        await runner.run(consolidate_prompt, session_id=None, timeout_seconds=600.0)
        logger.info("Nightly consolidate complete")
```

The only structural changes from Step 3's version are: (1) the docstring mentions the lock, (2) the entire body after `from datetime import timezone` is now indented under `async with _nightly_lock:`.

- [ ] **Step 10: Run the concurrency test to verify it passes**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestNightlyCompactThreshold -v`
Expected: 2 passed (the threshold test from Step 4 + the new concurrency test)

- [ ] **Step 11: Run full unit test suite**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/ -q`
Expected: all pass

- [ ] **Step 12: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add src/raisebull/heartbeat.py tests/unit/test_nightly_compact.py
git commit -m "$(cat <<'EOF'
feat: serialize nightly_compact via module-level asyncio.Lock

APScheduler max_instances=1 only protects the same job_id; the upcoming
manual /internal/nightly-compact/trigger endpoint dispatches via
asyncio.create_task and bypasses the scheduler entirely. Without a lock,
cron + trigger could run nightly_compact concurrently on the same DB,
double-calling /compact and racing update_compacted_at.

Test verifies that two concurrent runs result in exactly 2 runner.run
calls (1× /compact + 1× consolidate from run 1; run 2 sees the now-
compacted session as ineligible after taking the lock).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Dashboard Settings key

**Files:**
- Modify: `src/raisebull/admin/routes_settings.py:14-24` (`_ALLOWED_KEYS`)
- Test: `tests/integration/test_admin.py:212` (update `expected_keys`)
- Test: `tests/integration/test_admin.py` (add round-trip test)

**Goal:** Dashboard surfaces and persists `nightly_compact_threshold` like every other setting. The frontend auto-renders all keys from `GET /admin/api/settings`, so no UI changes needed.

- [ ] **Step 1: Update existing test expectations and add a new round-trip test**

Edit `tests/integration/test_admin.py` line 212. Change:

```python
        expected_keys = {"agent_name", "model", "max_steps", "auto_reply_timeout", "session_idle_timeout", "heartbeat_interval", "buffer_time", "nightly_compact_hour", "line_trigger_prefix"}
```

to:

```python
        expected_keys = {"agent_name", "model", "max_steps", "auto_reply_timeout", "session_idle_timeout", "heartbeat_interval", "buffer_time", "nightly_compact_hour", "nightly_compact_threshold", "line_trigger_prefix"}
```

Then add this new test method to the `TestSettings` class in `tests/integration/test_admin.py` (after `test_settings_put_persists_all_fields`):

```python
    @pytest.mark.asyncio
    async def test_put_settings_nightly_compact_threshold(self, client):
        await _login(client)
        resp = await client.put(
            "/admin/api/settings",
            json={"nightly_compact_threshold": "12345"},
        )
        assert resp.status_code == 200
        resp = await client.get("/admin/api/settings")
        data = resp.json()
        assert data["nightly_compact_threshold"] == "12345"

    @pytest.mark.asyncio
    async def test_put_settings_nightly_compact_threshold_rejects_non_numeric(self, client):
        """Garbage threshold values must be rejected at write-time so the dashboard
        never displays a value that nightly_compact() will silently ignore."""
        await _login(client)
        resp = await client.put(
            "/admin/api/settings",
            json={"nightly_compact_threshold": "abc"},
        )
        assert resp.status_code == 400
        # Confirm the bad value was NOT persisted
        resp = await client.get("/admin/api/settings")
        data = resp.json()
        assert data["nightly_compact_threshold"] != "abc"

    @pytest.mark.asyncio
    async def test_put_settings_nightly_compact_threshold_rejects_zero(self, client):
        await _login(client)
        resp = await client.put(
            "/admin/api/settings",
            json={"nightly_compact_threshold": "0"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_put_settings_nightly_compact_threshold_rejects_negative(self, client):
        await _login(client)
        resp = await client.put(
            "/admin/api/settings",
            json={"nightly_compact_threshold": "-100"},
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/integration/test_admin.py::TestSettings -v`
Expected: `test_get_settings_defaults` FAILs (key set mismatch). The 4 new round-trip / validation tests FAIL because the key isn't in `_ALLOWED_KEYS` yet (PUT silently drops the key, no validation runs, GET returns 200 with the missing key — so the rejection tests fail their `400` expectation).

- [ ] **Step 3: Add the key to `_ALLOWED_KEYS` AND wire up PUT validation**

In `src/raisebull/admin/routes_settings.py`, two changes:

(a) Modify the `_ALLOWED_KEYS` dict (lines 14-24) to add the new entry. Replace the existing dict with:

```python
_ALLOWED_KEYS: dict[str, tuple[str, str | None]] = {
    "agent_name": ("Agent", "AGENT_NAME"),
    "model": ("MiniMax-M2.7", "AGENT_MODEL"),
    "max_steps": ("100", "AGENT_MAX_STEPS"),
    "auto_reply_timeout": ("180", "AUTO_REPLY_TIMEOUT"),
    "session_idle_timeout": ("1800", "SESSION_IDLE_TIMEOUT"),
    "heartbeat_interval": ("1800", "HEARTBEAT_INTERVAL"),
    "buffer_time": ("10", "BUFFER_TIME"),
    "nightly_compact_hour": ("3", "NIGHTLY_COMPACT_HOUR"),
    "nightly_compact_threshold": ("50000", "NIGHTLY_COMPACT_THRESHOLD"),
    "line_trigger_prefix": ("小牛兒", "LINE_TRIGGER_PREFIX"),
}
```

(b) Add PUT-time validation. Modify the `put_settings` function (lines 57-69) — add a validation block that runs BEFORE the existing key-merging loop. Replace the existing function with:

```python
@router.put("")
async def put_settings(request: Request):
    body = await request.json()

    # Validate strict-positive int keys before persisting. Without this, garbage
    # values would be displayed by GET but silently ignored by nightly_compact()
    # (which validates internally and falls back to default), causing dashboard
    # vs runtime divergence.
    if "nightly_compact_threshold" in body:
        try:
            n = int(str(body["nightly_compact_threshold"]).strip())
        except (ValueError, TypeError, AttributeError):
            return JSONResponse(
                {"error": "nightly_compact_threshold must be a positive integer"},
                status_code=400,
            )
        if n <= 0:
            return JSONResponse(
                {"error": "nightly_compact_threshold must be > 0"},
                status_code=400,
            )

    path = _settings_path(request)
    current = _read_settings(path)
    for key in _ALLOWED_KEYS:
        if key in body:
            current[key] = str(body[key])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return {"ok": True}
```

Add `from fastapi.responses import JSONResponse` to the imports at the top of the file if it's not already there (run `grep JSONResponse src/raisebull/admin/routes_settings.py` to confirm — it's likely missing because the existing handlers all return dicts).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/integration/test_admin.py::TestSettings -v`
Expected: all 7 TestSettings tests pass (3 existing + 4 new: round-trip + 3 validation rejections)

- [ ] **Step 5: Run full integration suite**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/integration/ -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add src/raisebull/admin/routes_settings.py tests/integration/test_admin.py
git commit -m "$(cat <<'EOF'
feat: dashboard exposes nightly_compact_threshold + PUT validation

Adds the key to _ALLOWED_KEYS so GET/PUT /admin/api/settings round-trips
the value (auto-rendered by the existing Settings page — no UI changes).
Default 50000 / env NIGHTLY_COMPACT_THRESHOLD.

PUT validates the value is a strict-positive int and returns 400 on
garbage input. Without this, _read_settings() would echo back the bad
value while nightly_compact() (which validates internally) silently
falls through to the default — confusing dashboard vs runtime divergence.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Localhost-only gate + nightly-compact trigger endpoint

**Files:**
- Modify: `src/raisebull/main.py` (add `_require_localhost`, new endpoint, gate existing heartbeat trigger)
- Test: `tests/test_main.py` (new tests + adjust existing heartbeat trigger test)

**Goal:** Both `/internal/heartbeat/trigger` and the new `/internal/nightly-compact/trigger` are accessible only from `127.0.0.1`/`::1` callers. ASGITransport callers (in tests) are treated as localhost because `request.client` is `None`.

- [ ] **Step 1: Write the failing tests**

Edit `tests/test_main.py`. Add these new tests AFTER the existing `test_heartbeat_trigger_returns_ok`:

```python
@pytest.mark.asyncio
async def test_heartbeat_trigger_blocks_remote_client():
    """Non-localhost callers must get 403."""
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.run_event_check", new_callable=AsyncMock):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/heartbeat/trigger")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_nightly_compact_trigger_returns_ok():
    """Localhost caller (None client from ASGITransport default) gets 200."""
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.nightly_compact", new_callable=AsyncMock):
            from raisebull.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/internal/nightly-compact/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_nightly_compact_trigger_blocks_remote_client():
    """Non-localhost callers must get 403."""
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.nightly_compact", new_callable=AsyncMock):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/nightly-compact/trigger")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_nightly_compact_trigger_allows_ipv6_localhost():
    """::1 must be treated as localhost."""
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.nightly_compact", new_callable=AsyncMock):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("::1", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/nightly-compact/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/test_main.py -v -k "trigger"`
Expected: `test_heartbeat_trigger_blocks_remote_client` FAILS (currently no gate, returns 200), the 3 nightly_compact tests FAIL (endpoint doesn't exist, 404).

- [ ] **Step 3: Add the helper, the new endpoint, and gate the heartbeat trigger**

In `src/raisebull/main.py`, first add this import alongside the existing ones at the top of the routes section. Add the import for `nightly_compact` (search for `from raisebull.heartbeat import` and update the existing line):

Replace:
```python
from raisebull.heartbeat import start_heartbeat, run_event_check
```

with:
```python
from raisebull.heartbeat import start_heartbeat, run_event_check, nightly_compact
```

Then, immediately before the existing `@app.post("/internal/heartbeat/trigger")` route (around line 209), add the helper:

```python
def _require_localhost(request: Request) -> None:
    """Reject non-localhost callers with 403.

    Used by /internal/* endpoints that should only be invoked by:
      - The same Python process (e.g., heartbeat scheduler firing a task)
      - A shell inside the same container (`docker exec ... curl 127.0.0.1:8000/...`)
      - Test code via ASGITransport (request.client is None — treated as localhost)

    Tailnet IPs, the Docker bridge gateway IP, and any forwarded request from
    the published port are all rejected on purpose. If a future feature needs to
    expose nightly_compact via a dashboard "Run now" button, it must NOT bypass
    this gate by adding more allowed IPs — instead, add a NEW dashboard route
    (e.g., POST /admin/api/nightly-compact/run) that goes through the existing
    cookie-based auth_middleware and then calls nightly_compact() directly.
    The /internal/* path is reserved for in-process / in-container callers.
    """
    client = request.client
    if client is None:
        return
    if client.host in ("127.0.0.1", "::1", "localhost"):
        return
    raise HTTPException(status_code=403, detail="localhost only")
```

Then replace the existing heartbeat trigger (around line 209-213) with a version that takes `request` and calls the helper:

```python
@app.post("/internal/heartbeat/trigger")
async def heartbeat_trigger(request: Request) -> dict[str, Any]:
    """Manually trigger one heartbeat tick (for testing). Localhost only."""
    _require_localhost(request)
    asyncio.create_task(run_event_check(_runner, _sessions, push_fn=_heartbeat_push))
    return {"ok": True, "message": "heartbeat tick started"}


@app.post("/internal/nightly-compact/trigger")
async def nightly_compact_trigger(request: Request) -> dict[str, Any]:
    """Manually trigger nightly compact (for testing). Localhost only."""
    _require_localhost(request)
    asyncio.create_task(nightly_compact(_runner, _sessions, buffer=_message_buffer))
    return {"ok": True, "message": "nightly compact started"}
```

- [ ] **Step 4: Run new tests to verify they pass**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/test_main.py -v -k "trigger"`
Expected: all 5 trigger tests pass (existing `test_heartbeat_trigger_returns_ok` + 4 new)

- [ ] **Step 5: Run full main test file**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/test_main.py -v`
Expected: all pass

- [ ] **Step 6: Run full fast test suite**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/ tests/integration/ tests/test_main.py -q`
Expected: all pass (count = previous baseline + new tests added in tasks 1-5)

- [ ] **Step 7: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add src/raisebull/main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
feat: /internal/nightly-compact/trigger + localhost gate

Adds POST /internal/nightly-compact/trigger mirroring the heartbeat trigger
pattern, and locks both internal triggers to 127.0.0.1/::1 callers via a
shared _require_localhost helper. ASGITransport callers (tests) leave
request.client as None and are treated as localhost.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: End-to-end smoke test (real Claude CLI)

**Files:**
- Create: `tests/smoke/test_nightly_compact_live.py`

**Goal:** Spin up a real uvicorn server with a low threshold, seed two sessions (one above, one below), invoke `nightly_compact()` directly via the trigger endpoint, then verify the above-threshold session was compacted (new session_id, last_compacted_at stamped) while the below-threshold session is bit-for-bit untouched.

**Note:** This test makes 2-3 real Claude calls (1 `/compact` + 1 consolidate, plus 1 inject if buffer is non-empty). Use seeded sessions with ZERO buffer messages so we only burn 2 calls per run (`/compact` + consolidate).

- [ ] **Step 1: Create the smoke test file**

Create a new file `tests/smoke/test_nightly_compact_live.py` with the following content:

```python
"""Smoke test: nightly_compact with real Claude CLI.

Verifies the threshold gate works end-to-end:
- Session above threshold → compacted (new session_id, last_compacted_at stamped)
- Session below threshold → untouched

Run with:
    ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic \\
    ANTHROPIC_AUTH_TOKEN=<key> \\
    uv run pytest tests/smoke/test_nightly_compact_live.py -v -s

Costs ~2 Claude calls per invocation (1 /compact + 1 consolidate). The
below-threshold session never reaches the model.
"""
import asyncio
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

smoke = pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_BASE_URL") and os.environ.get("ANTHROPIC_AUTH_TOKEN")),
    reason="Requires ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN env vars",
)

THRESHOLD = 1000
SESSION_ABOVE = "web:smoke-above"
SESSION_BELOW = "web:smoke-below"
PORT_NAME = "nightly_compact_smoke"
PASSWORD = "smoke_nightly_compact_test"
# 2 real Claude calls (1× /compact + 1× consolidate). Each can take 60-120s on a
# slow link. 600s gives generous headroom — the test still bails fast if the
# trigger endpoint is broken because it polls every 3s and would never see
# last_compacted_at flip.
MAX_WAIT_SECONDS = 600
POLL_INTERVAL = 3


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Start a real uvicorn server with a low compact threshold."""
    tmp = tmp_path_factory.mktemp(PORT_NAME)
    workspace = tmp / "workspace"
    workspace.mkdir()
    for d in ("config", "context", "skills", "heartbeat"):
        (workspace / d).mkdir()

    # settings.json with low threshold so the seeded "above" session triggers
    (workspace / "config" / "settings.json").write_text(
        '{"nightly_compact_threshold": "' + str(THRESHOLD) + '"}'
    )
    # heartbeat.md must exist or the heartbeat scheduler errors
    (workspace / "heartbeat" / "heartbeat.md").write_text("## Smoke\n")
    (workspace / "heartbeat" / "last-run.json").write_text("{}")

    port = _find_free_port()
    sessions_db = str(tmp / "sessions.db")
    creds_db = str(tmp / "credentials.db")

    env = {
        **os.environ,
        "LINE_CHANNEL_SECRET": "dummy",
        "LINE_CHANNEL_ACCESS_TOKEN": "dummy",
        "DISCORD_BOT_TOKEN": "",
        # Long heartbeat so we don't conflict with our manual nightly trigger
        "HEARTBEAT_INTERVAL": "3600",
        "DB_PATH": sessions_db,
        "CREDENTIALS_DB_PATH": creds_db,
        "WORKSPACE": str(workspace),
        "ADMIN_PASSWORD": PASSWORD,
        "CLAUDE_MODEL": os.environ.get("ANTHROPIC_MODEL", "MiniMax-M2.7"),
    }

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "raisebull.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            r = httpx.get(f"{base_url}/health", timeout=2)
            if r.status_code == 200:
                break
        except httpx.ConnectError:
            pass
        time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError("Server failed to start")

    client = httpx.Client(base_url=base_url, timeout=30)
    resp = client.post("/admin/api/auth", json={"password": PASSWORD})
    assert resp.status_code == 200, "smoke server login failed"

    yield {
        "base_url": base_url,
        "client": client,
        "workspace": workspace,
        "proc": proc,
        "sessions_db": sessions_db,
    }

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    client.close()


def _seed_session(db_path: str, key: str, session_id: str, token_count: int) -> None:
    """Insert a session row directly into SQLite (bypasses live SessionStore)."""
    import sqlite3
    last_active = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sessions "
            "(key, session_id, domain, last_active, token_count, name, last_compacted_at) "
            "VALUES (?, ?, 'web', ?, ?, ?, NULL)",
            (key, session_id, last_active, token_count, key.split(":")[-1]),
        )
        conn.commit()
    finally:
        conn.close()


def _read_session(db_path: str, key: str) -> dict | None:
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT key, session_id, token_count, last_active, last_compacted_at "
            "FROM sessions WHERE key = ?",
            (key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _wait_for_compact(db_path: str, key: str, timeout: int = MAX_WAIT_SECONDS) -> dict:
    """Poll until the session has a non-null last_compacted_at, or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        row = _read_session(db_path, key)
        if row and row["last_compacted_at"] is not None:
            return row
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Session {key} was not compacted within {timeout}s")


@smoke
def test_nightly_compact_threshold_above_below(live_server):
    """Above-threshold session compacts; below-threshold session untouched.

    This is the critical end-to-end smoke: it proves _read_threshold() picks
    up settings.json AND nightly_compact() actually filters by it AND the
    below-threshold session is bit-for-bit unchanged after the run.
    """
    db_path = live_server["sessions_db"]

    # Seed: ABOVE has 5000 tokens, BELOW has 100 tokens. Threshold = 1000.
    _seed_session(db_path, SESSION_ABOVE, "smoke-orig-above-sid", token_count=5000)
    _seed_session(db_path, SESSION_BELOW, "smoke-orig-below-sid", token_count=100)

    above_before = _read_session(db_path, SESSION_ABOVE)
    below_before = _read_session(db_path, SESSION_BELOW)
    assert above_before is not None and above_before["last_compacted_at"] is None
    assert below_before is not None and below_before["last_compacted_at"] is None

    # Trigger nightly compact (localhost — server runs on 127.0.0.1)
    resp = httpx.post(f"{live_server['base_url']}/internal/nightly-compact/trigger", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Wait for the above-threshold session to be compacted
    above_after = _wait_for_compact(db_path, SESSION_ABOVE)

    # ABOVE: was compacted
    assert above_after["session_id"] != "smoke-orig-above-sid", \
        "above-threshold session should have a new session_id after /compact"
    assert above_after["last_compacted_at"] is not None
    assert above_after["last_compacted_at"] >= above_after["last_active"], \
        "last_compacted_at must be >= last_active to prevent re-compact loop"

    # BELOW: untouched (no waiting needed — should already be unchanged)
    below_after = _read_session(db_path, SESSION_BELOW)
    assert below_after["session_id"] == below_before["session_id"], \
        "below-threshold session_id must NOT change"
    assert below_after["last_compacted_at"] is None, \
        "below-threshold session must NOT be stamped"
    assert below_after["token_count"] == 100, \
        "below-threshold token_count must be unchanged"
    assert below_after["last_active"] == below_before["last_active"], \
        "below-threshold last_active must be unchanged"
```

- [ ] **Step 2: Run the smoke test**

Run:
```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && \
ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic \
ANTHROPIC_AUTH_TOKEN=<your-key> \
.venv/bin/python -m pytest tests/smoke/test_nightly_compact_live.py -v -s
```
Expected: 1 passed (will take 60-180 seconds because it waits for real `/compact` + consolidate Claude calls).

- [ ] **Step 3: Confirm fast tests still pass**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/ tests/integration/ tests/test_main.py -q`
Expected: full fast suite passes.

- [ ] **Step 4: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add tests/smoke/test_nightly_compact_live.py
git commit -m "$(cat <<'EOF'
test: smoke test for nightly_compact threshold (above + below)

End-to-end smoke that seeds two sessions (5000 tokens above, 100 tokens
below a 1000-token threshold), triggers nightly_compact via the new
internal endpoint, then verifies:
- Above session got a new claude session_id and last_compacted_at stamp
- Below session is bit-for-bit untouched (id, tokens, last_active, last_compacted_at)

Costs ~2 real Claude calls per run (1 /compact + 1 consolidate).
Skipped without ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN env vars.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: ~~Update CLAUDE.md docs~~ — PRE-DONE

**Status:** ✅ Already applied to `CLAUDE.md` and `README.md` BEFORE subagent-driven execution started, by the controller in commit `<filled-by-controller>`. The docs encode the EXPECTED end state — they are the target the implementer subagents must match. If after Tasks 1-6 the test count or behavior diverges from what `CLAUDE.md` already says, that's a bug to fix in the implementation, not in the docs.

**Subagents executing this plan: SKIP THIS TASK.** Move directly to the Manual Verification Checklist below.

For reference, the docs were updated with:
- Test count: `~229 fast + 17 smoke + 16 e2e` (was `~204 fast + 16 smoke`)
- Smoke files: 3 (added `nightly_compact_live`)
- Three new Key Decisions bullets: dynamic threshold, asyncio.Lock serialization, localhost gate intent
- New env var row: `NIGHTLY_COMPACT_THRESHOLD`
- README env var table: same `NIGHTLY_COMPACT_THRESHOLD` row added

---

## Manual Verification Checklist (after all 6 implementation tasks)

This isn't a code task — it's the live deploy verification we agreed on. After all commits land and the branch is pushed (pre-push hook will auto-run the fast suite):

1. **Deploy to samantha-wsl** — `ssh samantha-wsl 'cd ~/raise-a-bull && git pull && docker compose up -d --build'`
2. **Inflate a real session** — `docker exec bull-daniu sqlite3 /app/data/sessions.db "UPDATE sessions SET token_count=60000 WHERE key='discord:1481948275216093197'"`
3. **Lower threshold via dashboard** — Open `http://samantha-wsl.tail5a1118.ts.net:18888/admin/#/settings`, set `nightly_compact_threshold` to `55000`, save
4. **Trigger from inside the container** — `ssh samantha-wsl 'docker exec bull-daniu curl -sS -X POST http://127.0.0.1:8000/internal/nightly-compact/trigger'`
5. **Watch logs** — `ssh samantha-wsl 'docker logs -f bull-daniu'` until you see `Nightly compact: discord:1481948275216093197 (tokens=60000, threshold=55000)` followed by `Nightly consolidate complete`
6. **Verify DB state** — `docker exec bull-daniu sqlite3 /app/data/sessions.db "SELECT key, token_count, last_compacted_at FROM sessions WHERE key='discord:1481948275216093197'"` — last_compacted_at should be a fresh timestamp, token_count should have dropped (or be `output_tokens` from the compact)
7. **Verify localhost gate from outside** — From your laptop: `curl -X POST http://samantha-wsl.tail5a1118.ts.net:18888/internal/nightly-compact/trigger` → expected `403 localhost only`

If anything diverges, check `docker logs bull-daniu` for the threshold value (`Nightly compact: ... threshold=N`) — it should match what you set in step 3.

---

## Self-Review (v2, post-patch)

**Spec coverage:**
- ✅ Threshold runtime-configurable: Tasks 2, 3, 4
- ✅ DB > env > default precedence: Task 2
- ✅ Invalid values fall back to default: Task 2 (zero, negative, garbage in both env AND settings.json)
- ✅ Invalid values rejected at PUT-time so dashboard ↔ runtime stay consistent: Task 4 (3 rejection tests)
- ✅ Dashboard editability: Task 4 (auto-rendered, no UI work)
- ✅ Concurrent run protection: Task 3b (asyncio.Lock + serialization test)
- ✅ Trigger endpoint: Task 5
- ✅ Localhost gate (applied to BOTH triggers): Task 5
- ✅ Localhost gate intent documented (no IP allowlist hacks for future dashboard buttons): Task 5 docstring
- ✅ Smoke test verifies BOTH above + below threshold: Task 6
- ✅ Smoke test timeout generous enough for 2 real Claude calls: Task 6 (600s)

**Placeholder scan:** No TBD/TODO/"fill in details"; every step has runnable code or commands.

**Type consistency:** `_read_threshold(workspace: str) -> int` is consistent across Tasks 2, 3, and 6. `is_compact_eligible(session, key="", threshold=COMPACT_TOKEN_THRESHOLD)` signature matches between Task 1 (definition) and Task 3 (caller). `_require_localhost(request: Request) -> None` matches between definition and the two endpoint sites in Task 5. `_nightly_lock: asyncio.Lock` referenced consistently in Task 3b code + commit message. Settings key spelled `nightly_compact_threshold` consistently in routes_settings.py, smoke test, dashboard tests, and CLAUDE.md.

**Review-driven changes from v1:**
- v1 RED expectation in Task 3 was wrong (claimed both sessions would compact; actually neither would). Fixed.
- v1 had no concurrent-run protection — Sonnet didn't catch it but Opus did. Added Task 3b.
- v1 had no PUT validation, leaving a dashboard ↔ runtime divergence. Added 3 tests + JSONResponse import note in Task 4.
- v1 smoke test timeout (240s) was too aggressive for 2 real Claude calls. Bumped to 600s.
