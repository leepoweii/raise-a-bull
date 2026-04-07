# Post-Merge Cleanup From Final Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the test-coverage gaps and operational hardening items identified in the final Opus + Sonnet review of the nightly_compact-config-trigger feature, plus a few user-confirmed Tier 1 wins.

**Architecture:** Six independent fixes that share no code paths. Each fix has a clear test target and a single commit. Tier 1 wins (pre-push hook coverage, IPv4-mapped IPv6 in localhost gate, edge-case test pinning) are mechanical. Tier 2 design choices (atomic compact save, pre-push playwright integration, reverse-proxy CLAUDE.md warning) were settled during the prior brainstorm.

**Tech Stack:** Bash (git hooks), Python 3.14 + pytest + pytest-asyncio + aiosqlite, Playwright + uvicorn for e2e, FastAPI + Starlette `request.client`, Python stdlib `ipaddress`.

**Branch:** Create a new branch `cleanup/post-merge-final-review` from `main` (currently at `e6dea37`). Do NOT work directly on `main`.

---

## Background Context (read this before starting any task)

This plan addresses 6 specific items from the final Phase 5 + Opus/Sonnet review of the nightly_compact-config-trigger feature. The original feature is already merged to `main` at `e6dea37`. The full feature spec lives at `docs/superpowers/plans/2026-04-07-nightly-compact-config-trigger.md` (read the v3 changelog block at the top for the post-merge fix history).

**The 6 items being addressed (in execution order):**

1. **Tier 1A — Pre-push hook coverage gap.** Current `.git/hooks/pre-push` runs only `tests/unit/ tests/integration/` (263 tests). The `tests/test_*.py` root files (test_session, test_runner, test_discord_bot, test_recovery, test_main → 30 tests, total 293 fast) are silently excluded. A regression in those files passes through pre-push and reaches `main`.

2. **Pre-push playwright integration (Q1 from brainstorm).** The pre-push hook explicitly skips Playwright with a warning. The `fill('abc')` bug in commit `27ecb1d` would have been caught immediately by Playwright but instead shipped invisibly until Opus's final review caught it. Hook needs to auto-spawn a uvicorn fixture, run `npx playwright test`, and tear down.

3. **Tier 1B — IPv4-mapped IPv6 in localhost gate.** `_require_localhost` allowlists `("127.0.0.1", "::1", "localhost")` as string equality. Some Linux configs serve loopback as `::ffff:127.0.0.1` (IPv4-mapped IPv6); the gate would 403 it. Replace string check with `ipaddress.ip_address(host).is_loopback`.

4. **Crash recovery atomic compact save (Q2 from brainstorm).** `nightly_compact()` does `sessions.save(...)` then `sessions.update_compacted_at(...)` as two separate SQLite commits. A SIGTERM or process crash between the two leaves the session with a fresh `session_id` but `last_compacted_at = NULL`, so the next cron run treats it as new activity and re-compacts. Fix: add a new `SessionStore.save_with_compacted_at(...)` method that does a single SQL `UPDATE` of `session_id` + `domain` + `token_count` + `last_compacted_at` while PRESERVING `last_active` (because `last_active` is the user-facing "real activity" timestamp shown in discord/line/web displays — it must NOT jump to the compact time). Raises `KeyError` on missing row so `nightly_compact()` can log + skip the rare deleted-mid-compact race.

5. **Reverse-proxy CLAUDE.md warning (Q4 from brainstorm).** `_require_localhost` reads `request.client.host` (the real socket peer), so `X-Forwarded-For` header spoofing doesn't work today. But if anyone later runs uvicorn with `--proxy-headers` or `--forwarded-allow-ips`, the header would be trusted and the gate could be bypassed. Add a CLAUDE.md warning so future devs don't enable proxy headers without understanding the consequence.

6. **Tier 1C — Edge-case test pinning.** Three edge cases the code handles correctly today but no test pins:
   - `_coerce_threshold("  42  ")` (leading/trailing whitespace) → 42
   - `_coerce_threshold({"value": 42})` (nested dict, not str/int) → None (falls through)
   - `nightly_compact()` when `result.output_tokens is None` → uses `s["token_count"]` fallback (avoids overwriting token count with `None`)

**Key invariants you must NOT break:**
- `last_compacted_at >= last_active` after a successful compact (the re-compact-loop fix from `d0b8642`). The new atomic method preserves this by NOT touching `last_active` at all — UPDATE only writes the columns we name, so `last_active` remains the row's pre-existing real-user-activity timestamp (always strictly EARLIER than the compact, because the compact lock prevents concurrent user writes). DO NOT use `INSERT OR REPLACE` to write both fields with `compacted_at` — that would shift `last_active` to the cron run time and break user-facing displays in `discord_bot.py:434`, `webhook_line.py:144`, and `routes_chat.py:154`.
- All 5 existing tests in `tests/test_main.py::TestSettings` (and 3 other discord_push tests) must keep passing.
- Existing `SessionStore.save()` and `SessionStore.update_compacted_at()` must remain callable (don't delete them; future code might use them separately).
- Pre-push hook must remain skip-able with `git push --no-verify`.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `.git/hooks/pre-push` | Local git hook (untracked) — runs fast tests + e2e on push | 1, 2 |
| `scripts/git-hooks/pre-push` | Tracked canonical copy of the hook so other clones can install it | 1 |
| `scripts/git-hooks/install.sh` | One-line installer: `cp scripts/git-hooks/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push` | 1 |
| `src/raisebull/main.py` | `_require_localhost()` helper — replace string check with `ipaddress` | 3 |
| `tests/test_main.py` | Add IPv4-mapped IPv6 test | 3 |
| `src/raisebull/session.py` | Add `SessionStore.save_with_compacted_at()` method | 4 |
| `src/raisebull/heartbeat.py` | `nightly_compact()` — call new atomic method instead of save+update | 4 |
| `tests/unit/test_nightly_compact.py` | Tests for atomic save method + 3 edge-case tests | 4, 6 |
| `CLAUDE.md` | Reverse-proxy warning + hook setup instructions | 5, 1 |

**Why split this way:** Each task touches a small focused set of files. Tasks 1+2 share the pre-push hook (one tracked file, two commits adding capability incrementally). Task 3 is contained to one helper function + one test. Task 4 is the only multi-file change (session.py + heartbeat.py + tests). Tasks 5 and 6 are doc-only or test-only.

---

## Task 1: Pre-push hook — root tests + tracked install

**Files:**
- Create: `scripts/git-hooks/pre-push`
- Create: `scripts/git-hooks/install.sh`
- Modify: `.git/hooks/pre-push` (local, untracked — install via the script)
- Modify: `CLAUDE.md` (add hook setup section)

**Goal:** Pre-push hook runs all 293 fast tests (not just the 263-test subset), and the hook itself lives under version control so other clones can install it in one command.

- [ ] **Step 1: Create the tracked hook file**

The `scripts/git-hooks/` directory does NOT exist yet. Most Write/Create tools auto-create parent dirs, but if your tool doesn't, run this first:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
mkdir -p scripts/git-hooks
```

Then create `scripts/git-hooks/pre-push` with this exact content:

```bash
#!/bin/bash
# Pre-push hook: run all tests before pushing
# Skip with: git push --no-verify
#
# Lives at scripts/git-hooks/pre-push (tracked) — copied to .git/hooks/pre-push
# by scripts/git-hooks/install.sh after clone.

set -e

cd "$(git rev-parse --show-toplevel)"

echo "🧪 Running all tests before push..."

# Fast tests: every test under tests/ except tests/e2e (Playwright) and
# tests/smoke (real Claude API calls). This covers all unit, integration,
# and root-level test files (test_session, test_runner, test_discord_bot,
# test_recovery, test_main) — 293 tests total as of e6dea37.
#
# set -e makes pytest's non-zero exit abort the script immediately, so no
# manual `if [ $? -ne 0 ]` check is needed.
echo "--- Fast tests (unit + integration + root) ---"
.venv/bin/pytest tests/ --ignore=tests/e2e --ignore=tests/smoke -q --tb=short

# E2E tests skipped here — Task 2 will add them
if command -v npx > /dev/null 2>&1 && [ -f "playwright.config.ts" ]; then
    echo ""
    echo "--- E2E tests (Playwright) ---"
    echo "⚠️  E2E tests require a running server. Skipping in pre-push."
    echo "   Run manually: npx playwright test"
fi

echo ""
echo "✅ All tests passed. Pushing..."
```

- [ ] **Step 2: Create the install script**

Create `scripts/git-hooks/install.sh` with this exact content:

```bash
#!/bin/bash
# Install repo git hooks into .git/hooks/.
# Run once after cloning, or after pulling hook updates.
#
# Currently only pre-push is tracked. Add new hook names to the HOOKS variable
# below if more get tracked later.

set -e

cd "$(git rev-parse --show-toplevel)"

if [ ! -d .git/hooks ]; then
    echo "❌ .git/hooks directory not found — are you in a git working tree?"
    exit 1
fi

HOOKS="pre-push"
for hook in $HOOKS; do
    src="scripts/git-hooks/$hook"
    if [ ! -f "$src" ]; then
        echo "❌ $src not found — repo missing tracked hook source"
        exit 1
    fi
    target=".git/hooks/$hook"
    cp "$src" "$target"
    chmod +x "$target"
    echo "✅ Installed $hook → $target"
done
```

Make both files executable:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
chmod +x scripts/git-hooks/pre-push scripts/git-hooks/install.sh
```

- [ ] **Step 3: Install the new hook locally and verify it works**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
./scripts/git-hooks/install.sh
.git/hooks/pre-push < /dev/null
```

Expected: hook prints `🧪 Running all tests before push...`, then `--- Fast tests (unit + integration + root) ---`, then `293 passed` (not 263), then `✅ All tests passed. Pushing...`. Exit code 0.

If the count is not 293, run `.venv/bin/pytest tests/ --ignore=tests/e2e --ignore=tests/smoke --collect-only -q | tail -3` to confirm the actual count and update the comment in `scripts/git-hooks/pre-push` to match.

- [ ] **Step 4: Add CLAUDE.md hook setup section**

In `CLAUDE.md`, find the `## Tests` section (around line 134-165). Use the Edit tool to add a new `### Git Hooks` subsection immediately AFTER the existing `### Test Structure` block, BEFORE the `---` separator that leads into `## Key Decisions`.

The exact text to insert (use the Edit tool's `new_string` parameter — the literal triple-backticks below are the actual characters that should appear in CLAUDE.md, NOT escaped):

````
### Git Hooks

Local pre-push hook lives at `scripts/git-hooks/pre-push` (tracked) and runs the full fast test suite (293 tests, ~3s) before allowing a push. Install after clone with:

```bash
./scripts/git-hooks/install.sh
```

Skip the hook for emergency pushes: `git push --no-verify`. Do NOT skip routinely — the hook caught real bugs (fill('abc') Playwright crash, threshold validation regressions) during the nightly_compact feature work.
````

The wrapping fence above uses 4 backticks so the inner 3-backtick `bash` block renders correctly inside the plan. When you copy the content, take only what's BETWEEN the 4-backtick fences — the inner triple-backticks ARE part of the CLAUDE.md content.

- [ ] **Step 5: Run the full fast suite manually to verify the hook didn't break anything**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/ --ignore=tests/e2e --ignore=tests/smoke -q
```

Expected: `293 passed` (or the exact current count — if drift happened since this plan was written, the number may be 293-296). No failures.

- [ ] **Step 6: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add scripts/git-hooks/pre-push scripts/git-hooks/install.sh CLAUDE.md
git commit -m "$(cat <<'EOF'
test: pre-push hook covers all 293 fast tests + tracked install

Final review caught that .git/hooks/pre-push only ran tests/unit/ +
tests/integration/ (263 tests), silently excluding the 30 root-level
test files (test_session, test_runner, test_discord_bot, test_recovery,
test_main). Regressions in any of those would pass pre-push and reach
main.

Fix: hook now runs `pytest tests/ --ignore=tests/e2e --ignore=tests/smoke`
covering all 293 fast tests. Hook content tracked at
scripts/git-hooks/pre-push so other clones can install via
scripts/git-hooks/install.sh. CLAUDE.md gains a Git Hooks section
documenting the install command.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pre-push hook — Playwright e2e integration

**Files:**
- Modify: `scripts/git-hooks/pre-push` (extend with e2e block + trap cleanup + port-collision check)
- Modify: `tests/e2e/dashboard.spec.ts` (add `test.skip` markers to LLM-requiring describes)
- Re-install: `.git/hooks/pre-push` via `./scripts/git-hooks/install.sh` after edit

**Goal:** Pre-push hook auto-spawns a uvicorn fixture, runs the LLM-free Playwright tests (Auth + Navigation + Status + Settings = 9 tests), tears down via `trap` so cleanup ALWAYS runs even on failure. Catches the `fill('abc')` class of bug while keeping the push fast (~10-15s) and free of real Claude CLI calls. The Web Chat (5 tests) and File Upload (5 tests) describes are skipped via env var because they need a real authenticated `claude` CLI and cost real tokens.

- [ ] **Step 1: Add `test.skip` markers to LLM-requiring describes in dashboard.spec.ts**

The hook will set `SKIP_LLM_E2E=1` when running. Edit `tests/e2e/dashboard.spec.ts`. Find the `Web Chat` describe block (line 199) and add a `test.skip(condition, reason)` call at the TOP of the describe body, BEFORE the existing `test.beforeEach`. Per Playwright docs, this conditional form skips ALL tests inside the describe when the condition is true (whereas `test.describe.skip(...)` is unconditional, which we don't want — manual `npx playwright test` should still run these). The current block starts:

```typescript
test.describe('Web Chat', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.click('a:has-text("Chat")');
  });

  test('creates new session', async ({ page }) => {
```

Add the skip BEFORE the `beforeEach`:

```typescript
test.describe('Web Chat', () => {
  test.skip(
    process.env.SKIP_LLM_E2E === '1',
    'Skipped via SKIP_LLM_E2E=1 — these tests need a real authenticated `claude` CLI and cost real tokens. Run manually with `npx playwright test --grep "Web Chat"`.'
  );

  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.click('a:has-text("Chat")');
  });

  test('creates new session', async ({ page }) => {
```

Then find the `File Upload` describe block (line 280) and add the same skip marker. Current block:

```typescript
test.describe('File Upload', () => {
```

Becomes:

```typescript
test.describe('File Upload', () => {
  test.skip(
    process.env.SKIP_LLM_E2E === '1',
    'Skipped via SKIP_LLM_E2E=1 — these tests need a real authenticated `claude` CLI and cost real tokens. Run manually with `npx playwright test --grep "File Upload"`.'
  );

```

The `test.skip(condition, reason)` form at the top of a describe block skips ALL tests inside it when the condition is true.

- [ ] **Step 2: Extend the tracked hook with the e2e block (trap-based cleanup + port-collision check)**

Edit `scripts/git-hooks/pre-push`. Find this block:

```bash
# E2E tests skipped here — Task 2 will add them
if command -v npx &> /dev/null && [ -f "playwright.config.ts" ]; then
    echo ""
    echo "--- E2E tests (Playwright) ---"
    echo "⚠️  E2E tests require a running server. Skipping in pre-push."
    echo "   Run manually: npx playwright test"
fi
```

Replace it with this version. It uses `trap` to guarantee cleanup runs even when `set -e` aborts on a failed playwright invocation, checks for a port collision before spawning uvicorn, and sets `SKIP_LLM_E2E=1` so Web Chat + File Upload describes auto-skip:

```bash
# E2E tests (Playwright) — auto-spawn uvicorn fixture, run LLM-free tests, tear down.
# Trap guarantees cleanup runs even if pytest/playwright/curl fails under set -e.
# SKIP_LLM_E2E=1 makes Web Chat + File Upload describes auto-skip (those need
# a real authenticated `claude` CLI and cost real tokens — run manually instead).
# Set SKIP_E2E=1 to bypass the entire e2e block for emergency pushes.
if [ "$SKIP_E2E" = "1" ]; then
    echo ""
    echo "--- E2E tests (Playwright) ---"
    echo "⚠️  Skipped via SKIP_E2E=1"
elif command -v npx > /dev/null 2>&1 && [ -f "playwright.config.ts" ]; then
    echo ""
    echo "--- E2E tests (Playwright, LLM-free subset) ---"

    # Port collision pre-check — if anything is already on 8766 (matches the
    # port playwright.config.ts expects), bail with a clear error rather than
    # silently running playwright against the wrong server.
    if lsof -ti:8766 > /dev/null 2>&1; then
        EXISTING_PID=$(lsof -ti:8766)
        echo "❌ Port 8766 is already in use by PID(s): $EXISTING_PID"
        echo "   Either kill the existing process (lsof -ti:8766 then kill <pid>)"
        echo "   or skip e2e for this push: SKIP_E2E=1 git push"
        exit 1
    fi

    # Reserve a temp workspace + uvicorn pid placeholder
    TMP_WS=$(mktemp -d)
    UVICORN_PID=""

    # Trap MUST be installed BEFORE the uvicorn spawn so an early failure
    # (e.g., uvicorn doesn't start) still cleans up the tmpdir.
    cleanup() {
        if [ -n "$UVICORN_PID" ]; then
            kill "$UVICORN_PID" 2>/dev/null || true
            wait "$UVICORN_PID" 2>/dev/null || true
        fi
        rm -rf "$TMP_WS"
    }
    trap cleanup EXIT INT TERM

    # Workspace fixture
    mkdir -p "$TMP_WS/config" "$TMP_WS/heartbeat"
    echo '{"nightly_compact_threshold":"50000"}' > "$TMP_WS/config/settings.json"
    echo '## prepush' > "$TMP_WS/heartbeat/heartbeat.md"
    echo '{}' > "$TMP_WS/heartbeat/last-run.json"

    # Spawn uvicorn on 127.0.0.1:8766 (matches playwright.config.ts baseURL)
    ADMIN_PASSWORD=demo123 \
    LINE_CHANNEL_SECRET=dummy \
    LINE_CHANNEL_ACCESS_TOKEN=dummy \
    DISCORD_BOT_TOKEN= \
    HEARTBEAT_INTERVAL=3600 \
    WORKSPACE="$TMP_WS" \
    DB_PATH="$TMP_WS/sessions.db" \
    CREDENTIALS_DB_PATH="$TMP_WS/credentials.db" \
    .venv/bin/python -m uvicorn raisebull.main:app \
        --host 127.0.0.1 --port 8766 \
        > "$TMP_WS/uvicorn.log" 2>&1 &
    UVICORN_PID=$!

    # Wait for /health (max 15s)
    UVICORN_READY=0
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if curl -sS http://127.0.0.1:8766/health > /dev/null 2>&1; then
            UVICORN_READY=1
            break
        fi
        sleep 1
    done

    if [ "$UVICORN_READY" != "1" ]; then
        echo "❌ uvicorn failed to start on :8766 within 15s"
        echo "--- last 20 lines of $TMP_WS/uvicorn.log ---"
        tail -20 "$TMP_WS/uvicorn.log" || true
        exit 1   # trap fires and runs cleanup
    fi

    # Run the LLM-free subset. set +e around playwright so we capture the
    # exit code instead of letting set -e abort before our message.
    set +e
    SKIP_LLM_E2E=1 npx playwright test --reporter=line
    PLAYWRIGHT_EXIT=$?
    set -e

    if [ $PLAYWRIGHT_EXIT -ne 0 ]; then
        echo "❌ Playwright tests failed. Push aborted."
        echo "   Run full e2e manually: npx playwright test"
        echo "   Skip e2e block:        SKIP_E2E=1 git push"
        exit 1   # trap fires and runs cleanup
    fi
    # trap fires on normal exit too — uvicorn killed and tmpdir removed
fi
```

Note the `set +e` / `set -e` brackets around `npx playwright test` — this is the only place we want the script to KEEP RUNNING on a non-zero exit so we can capture `$?` and print the user-friendly error message before bailing. The `trap` ensures cleanup happens regardless.

- [ ] **Step 3: Re-install the hook locally**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
./scripts/git-hooks/install.sh
```

Expected: `✅ Installed pre-push → .git/hooks/pre-push`.

- [ ] **Step 4: Run the hook manually to verify the e2e block works end-to-end**

Before running, make sure nothing is already on :8766 (e.g., a forgotten manual uvicorn from earlier dev):

```bash
lsof -ti:8766 && echo "⚠️  port busy — kill the existing process before proceeding" || echo "port free"
```

Then:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
.git/hooks/pre-push < /dev/null
```

Expected output sequence:
1. `🧪 Running all tests before push...`
2. `--- Fast tests (unit + integration + root) ---`
3. `293 passed` (or current count — will grow as later tasks add tests)
4. `--- E2E tests (Playwright, LLM-free subset) ---`
5. Playwright runs (~5-15s) — should print `9 passed, 10 skipped` (9 non-LLM tests run, 10 LLM-requiring tests in Web Chat + File Upload describes skipped via SKIP_LLM_E2E=1)
6. `✅ All tests passed. Pushing...`
7. Exit code 0
8. After the hook exits, verify cleanup ran: `lsof -ti:8766` should print nothing. The workspace tmpdir is harder to verify directly because `mktemp -d` uses platform-specific paths (`/var/folders/...` on macOS, `/tmp/tmp.XXX` on Linux). The trap-test in Step 5 below provides a more reliable cleanup check by capturing the exact path before the hook runs and asserting it's gone after.

If Playwright fails because browser binaries aren't installed, run `npx playwright install --with-deps chromium` first.

- [ ] **Step 5: Verify the trap cleanup runs even on failure**

This is the critical correctness check — if playwright fails, the uvicorn process MUST be cleaned up (otherwise the next push will fail the port-collision check). Simulate a failure by introducing a temporary broken assertion:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull

# Temporarily break one test. The sed pattern uses \x27 (which is a single
# quote) to escape literal single quotes inside the outer single-quoted
# script. Verified to work on macOS BSD sed (Darwin 25.2.0+) and GNU sed.
sed -i.bak 's/await expect(page.locator(\x27.sidebar-header\x27)).toBeVisible()/await expect(page.locator(".sidebar-header")).toContainText("THIS_WILL_NEVER_MATCH_XYZ123")/' tests/e2e/dashboard.spec.ts

# Confirm the substitution actually happened (sed silently makes no change
# if the pattern doesn't match — verify by grep before running the hook)
if ! grep -q "THIS_WILL_NEVER_MATCH_XYZ123" tests/e2e/dashboard.spec.ts; then
    mv tests/e2e/dashboard.spec.ts.bak tests/e2e/dashboard.spec.ts
    echo "❌ sed substitution failed — the target line may have moved. Verify manually."
    exit 1
fi

# Run the hook — should FAIL on the broken test but still clean up
.git/hooks/pre-push < /dev/null
HOOK_EXIT=$?

# Restore the spec file IMMEDIATELY (before any other check, so we don't leave
# the repo in a broken state if a later assertion exits early)
mv tests/e2e/dashboard.spec.ts.bak tests/e2e/dashboard.spec.ts

# Verify cleanup ran
echo "hook exit: $HOOK_EXIT (should be non-zero, indicating playwright failed)"
if [ $HOOK_EXIT -eq 0 ]; then
    echo "❌ FAIL: hook exited 0 but the broken test should have caused failure"
    exit 1
fi
if lsof -ti:8766 > /dev/null 2>&1; then
    echo "❌ FAIL: uvicorn leaked on :8766 — the trap did not clean up"
    LEAKED_PID=$(lsof -ti:8766)
    echo "   Manual cleanup: kill $LEAKED_PID"
    exit 1
fi
echo "✅ trap cleanup verified — uvicorn was killed even though playwright failed"
```

Expected: hook exits non-zero, `lsof -ti:8766` prints nothing. The dashboard.spec.ts is restored. If uvicorn is still running after a failed hook, the trap is broken.

Note on tmpdir cleanup: the hook's internal `$TMP_WS` lives in `/var/folders/...` on macOS or `/tmp/tmp.XXXXX` on Linux. We don't try to verify the tmpdir was removed because: (a) the trap calls `rm -rf "$TMP_WS"` which is a single-line correctness operation that's hard to get wrong, (b) capturing the path from outside the hook's subshell is awkward, (c) a leaked tmpdir is ~20KB cosmetic waste vs the leaked uvicorn which is a real port-collision blocker. Uvicorn cleanup is the high-value check.

- [ ] **Step 6: Verify the SKIP_E2E escape hatch works**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
SKIP_E2E=1 .git/hooks/pre-push < /dev/null
```

Expected: fast tests run (293+), e2e block prints `⚠️  Skipped via SKIP_E2E=1`, exits 0 in ~3s.

- [ ] **Step 7: Update CLAUDE.md hook section to mention SKIP_E2E and SKIP_LLM_E2E**

In `CLAUDE.md` `### Git Hooks` subsection (added in Task 1), find this paragraph:

```
Skip the hook for emergency pushes: git push --no-verify. Do NOT skip routinely — the hook caught real bugs (fill('abc') Playwright crash, threshold validation regressions) during the nightly_compact feature work.
```

Replace it with this paragraph:

```
The hook also auto-runs the LLM-free Playwright e2e subset (~5-15s) — it spawns a temporary uvicorn fixture on 127.0.0.1:8766 (with a port-collision pre-check), runs `SKIP_LLM_E2E=1 npx playwright test`, and tears down via a shell trap so cleanup runs even on test failure. The Web Chat + File Upload describes (10 tests) auto-skip via SKIP_LLM_E2E because they need a real authenticated `claude` CLI and cost real tokens — run them manually with `npx playwright test --grep "Web Chat|File Upload"`. Escape hatches: `SKIP_E2E=1 git push` skips the e2e block entirely, `git push --no-verify` skips the whole hook. Use sparingly — the hook caught real bugs (fill('abc') Playwright crash, threshold validation regressions) during the nightly_compact feature work.
```

- [ ] **Step 8: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add scripts/git-hooks/pre-push tests/e2e/dashboard.spec.ts CLAUDE.md
git commit -m "$(cat <<'EOF'
test: pre-push hook auto-runs LLM-free Playwright e2e subset

Final review caught that the fill('abc') bug in 27ecb1d shipped
invisibly because the pre-push hook explicitly skipped Playwright
("requires a running server"). Now the hook spawns a temporary
uvicorn fixture (dummy LINE creds, tmp workspace, port 8766),
waits for /health, runs the 9 LLM-free tests (Auth + Navigation +
Status + Settings), tears down via a shell trap.

Web Chat (5 tests) and File Upload (5 tests) describes auto-skip
via SKIP_LLM_E2E=1 because they need a real authenticated `claude`
CLI and cost real tokens — run them manually with
`npx playwright test --grep "Web Chat|File Upload"`.

Robustness measures from final review:
- trap EXIT INT TERM guarantees uvicorn kill + tmpdir cleanup even
  when set -e aborts on a failed playwright invocation
- lsof :8766 pre-check refuses to start if port already busy (avoids
  false-passing against a stale uvicorn from earlier dev)
- set +e brackets around `npx playwright test` so we can capture
  the exit code and print a user-friendly error before bailing

SKIP_E2E=1 escape hatch for emergency pushes. CLAUDE.md updated.

Adds ~5-15s per push but eliminates the entire class of "e2e
test never actually ran" bugs.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: IPv4-mapped IPv6 in localhost gate

**Files:**
- Modify: `src/raisebull/main.py` (`_require_localhost` function around line 162-184)
- Modify: `tests/test_main.py` (add 1 new test, then update existing tests for symmetry)

**Goal:** `_require_localhost` accepts IPv4-mapped IPv6 loopback (`::ffff:127.0.0.1`) which some Linux configurations serve. Replace string allowlist with `ipaddress.ip_address(host).is_loopback`.

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_main.py` immediately AFTER the existing `test_nightly_compact_trigger_allows_ipv6_localhost` test:

```python
@pytest.mark.asyncio
async def test_nightly_compact_trigger_allows_ipv4_mapped_ipv6_localhost():
    """::ffff:127.0.0.1 (IPv4-mapped IPv6 loopback) must be treated as localhost.

    Some Linux dual-stack uvicorn configurations serve loopback this way. The
    string-equality allowlist would 403 it. Using ipaddress.ip_address().is_loopback
    correctly recognizes it as a loopback address.
    """
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.nightly_compact", new_callable=AsyncMock):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("::ffff:127.0.0.1", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/nightly-compact/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
```

- [ ] **Step 2: Run the new test to verify it FAILS**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/test_main.py::test_nightly_compact_trigger_allows_ipv4_mapped_ipv6_localhost -v
```

Expected: FAIL with `assert 403 == 200`. The current string allowlist `("127.0.0.1", "::1", "localhost")` does not include `::ffff:127.0.0.1` so the gate raises HTTPException(403).

- [ ] **Step 3: Add top-level `import ipaddress` and replace the string allowlist**

In `src/raisebull/main.py`, first add `import ipaddress` to the top-level imports. Find the existing import block near the top of the file (the one that has `import asyncio`, `import logging`, `import os`, etc.) and add `import ipaddress` alongside them in alphabetical order (between `import asyncio` and `import logging`). Confirm with `grep -n "^import ipaddress" src/raisebull/main.py` that the import is at module scope, not inside any function.

Then find the `_require_localhost` function (around lines 162-184). The current implementation uses string equality:

```python
def _require_localhost(request: Request) -> None:
    """Reject non-localhost callers with 403.
    ...
    """
    client = request.client
    if client is None:
        return
    if client.host in ("127.0.0.1", "::1", "localhost"):
        return
    raise HTTPException(status_code=403, detail="localhost only")
```

Replace with this version. Uses `ipaddress.ip_address().is_loopback` which on Python 3.12+ correctly recognizes `127.0.0.1`, `::1`, AND IPv4-mapped IPv6 like `::ffff:127.0.0.1` (verified locally on Python 3.14 — the project's pinned version). The dead `"localhost"` string branch is removed because Starlette resolves `request.client.host` to a peer IP, never the hostname — that branch was unreachable code masquerading as "defensive".

```python
def _require_localhost(request: Request) -> None:
    """Reject non-localhost callers with 403.

    Used by /internal/* endpoints that should only be invoked by:
      - The same Python process (e.g., heartbeat scheduler firing a task)
      - A shell inside the same container (`docker exec ... curl 127.0.0.1:8000/...`)
      - Test code via ASGITransport (client defaults to ("127.0.0.1", 123) in
        httpx 0.28+ so the loopback check accepts it)

    Tailnet IPs, the Docker bridge gateway IP, and any forwarded request from
    the published port are all rejected on purpose. If a future feature needs to
    expose nightly_compact via a dashboard "Run now" button, it must NOT bypass
    this gate by adding more allowed IPs — instead, add a NEW dashboard route
    (e.g., POST /admin/api/nightly-compact/run) that goes through the existing
    cookie-based auth_middleware and then calls nightly_compact() directly.
    The /internal/* path is reserved for in-process / in-container callers.

    Loopback recognition uses ipaddress.ip_address().is_loopback which on
    Python 3.12+ correctly handles 127.0.0.1, ::1, AND IPv4-mapped IPv6 like
    ::ffff:127.0.0.1 (which some Linux dual-stack uvicorn configs serve as
    the loopback address).
    """
    client = request.client
    if client is None:
        return
    try:
        if ipaddress.ip_address(client.host).is_loopback:
            return
    except ValueError:
        pass  # not a parseable IP — fall through to 403
    raise HTTPException(status_code=403, detail="localhost only")
```

- [ ] **Step 4: Run the new test + ALL trigger tests to verify everything passes**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/test_main.py -v -k "trigger or discord_push"
```

Expected: 11 passed (6 trigger tests + 5 discord_push tests). Specifically, the new `test_nightly_compact_trigger_allows_ipv4_mapped_ipv6_localhost` must now pass, AND all other localhost-gate tests must still pass (regression check on the gate refactor).

- [ ] **Step 5: Run the full fast suite**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/ --ignore=tests/e2e --ignore=tests/smoke -q
```

Expected: 294 passed (293 baseline + 1 new). No failures.

- [ ] **Step 6: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add src/raisebull/main.py tests/test_main.py
git commit -m "$(cat <<'EOF'
fix: localhost gate accepts IPv4-mapped IPv6 loopback

Final review (Opus) flagged that ::ffff:127.0.0.1 — the IPv4-mapped
IPv6 form of localhost — would be 403'd by the string allowlist
("127.0.0.1", "::1", "localhost"). Some Linux dual-stack uvicorn
configurations serve loopback this way. Today the deployment uses
pure --host 127.0.0.1 so safe, but a future --host :: switch would
silently break the gate.

Fix: use ipaddress.ip_address(host).is_loopback (Python 3.12+ handles
all loopback variants including ::ffff:127.0.0.1). Verified locally
on the project's pinned Python 3.14.

Also: removed the dead `client.host == "localhost"` string branch.
Starlette resolves request.client.host to a parsed IP, never the
hostname literal — that branch was unreachable code masquerading as
defensive. Moved `import ipaddress` to top-level alongside the other
stdlib imports for consistency.

New test pins ::ffff:127.0.0.1 → 200.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Atomic compact save (crash recovery)

**Files:**
- Modify: `src/raisebull/session.py` (add `save_with_compacted_at` method around line 90)
- Modify: `src/raisebull/heartbeat.py` (`nightly_compact` lines 218-227)
- Modify: `tests/unit/test_nightly_compact.py` (extend `TestSessionStoreUpdateCompactedAt` or add new class)

**Goal:** Replace the two-statement `save()` + `update_compacted_at()` sequence with a single atomic SQL `UPDATE` that rotates `session_id`, refreshes `domain` + `token_count`, AND stamps `last_compacted_at` in one statement. UPDATE is buffered until `await commit()`; a process crash between `execute()` and `commit()` leaves the WAL with an uncommitted write that's discarded on reopen — so either the old row or the new row is visible, never a partial state where `session_id` rotates but `last_compacted_at` is NULL.

**Why UPDATE not INSERT OR REPLACE:** UPDATE only touches the columns we name. Crucially, it PRESERVES `last_active` — the row's user-facing "time of most recent real activity" timestamp. `last_active` is read by `discord_bot.py:434` (displays "Last active: ..." to users), `webhook_line.py:144` (same), and `routes_chat.py:154` (uses it as `created_at` for in-memory web sessions). If `nightly_compact()` overwrote `last_active` with the compact time, every user would see their displays jump to 03:00 AM after the cron — confusing and incorrect, since the column means "what the user did", not "what the cron touched".

**Timestamp invariant:** Because `last_active` is preserved (always strictly EARLIER than the compact time, since the compact lock prevents concurrent user writes), the invariant `last_compacted_at > last_active` holds strictly after every successful compact. `is_compact_eligible()` (heartbeat.py:50) checks `session["last_active"] <= last_compacted` and correctly returns False, preventing the re-compact loop from `d0b8642`.

**Missing-row handling:** UPDATE on a deleted key matches zero rows. The new method checks `cursor.rowcount` and raises `KeyError` so the caller knows the row was removed between `is_compact_eligible()` and now (rare race with `session.clear()`). `nightly_compact()` catches the `KeyError`, logs a warning, and skips to the next eligible session — the compact's `/compact` Claude call is wasted in this race window but no DB state is corrupted.

- [ ] **Step 1: Write the failing test**

Add this new test class to `tests/unit/test_nightly_compact.py` (append after the existing `TestNightlyCompactLogging` class):

```python
class TestSessionStoreSaveWithCompactedAt:
    """Verifies that SessionStore.save_with_compacted_at writes both session_id
    and last_compacted_at in a single atomic statement, eliminating the
    crash-recovery race where a SIGTERM between save() and update_compacted_at()
    leaves the session with a fresh session_id but no compaction stamp.
    """

    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_updates_session_id_and_compacted_at_preserves_last_active(self, store):
        """The atomic UPDATE rotates session_id + token_count + domain + sets
        last_compacted_at, but DOES NOT touch last_active. last_active is the
        user-facing 'last real activity' timestamp displayed in
        discord_bot.py:434, webhook_line.py:144, and used as created_at in
        routes_chat.py:154 — touching it during a background compact would
        shift those displays to the cron's 03:00 AM run time."""
        # Pre-save creates the row with last_active = datetime.now() at save time
        await store.save("web:test", session_id="orig-sid", domain="web", token_count=5000)
        before = await store.get("web:test")
        original_last_active = before["last_active"]
        assert before["last_compacted_at"] is None  # baseline: not yet compacted

        # Compact runs — atomic UPDATE of session_id + last_compacted_at
        await store.save_with_compacted_at(
            "web:test",
            session_id="post-compact-sid",
            domain="web",
            token_count=900,
            compacted_at="2026-04-08T03:00:00+00:00",
        )

        row = await store.get("web:test")
        assert row["session_id"] == "post-compact-sid"   # rotated
        assert row["token_count"] == 900                 # updated
        assert row["domain"] == "web"
        assert row["last_compacted_at"] == "2026-04-08T03:00:00+00:00"
        # CRITICAL: last_active is UNCHANGED — preserves user-display semantics
        assert row["last_active"] == original_last_active

    @pytest.mark.asyncio
    async def test_invariant_compacted_at_strictly_after_last_active(self, store):
        """The re-compact-loop fix from d0b8642: is_compact_eligible() at
        heartbeat.py:50 returns False when `session["last_active"] <= last_compacted`
        (no new user activity since the compact). With UPDATE-based save, the
        invariant holds STRICTLY (compacted_at > last_active) because:
          - last_active is set by save() at time T1 (real user activity)
          - compacted_at is captured at time T2 > T1 (compact happened later)
          - The compact lock prevents user activity from racing the compact
        """
        # Save a row at the wall-clock "now"
        await store.save("web:test", session_id="sid", domain="web", token_count=5000)

        # Compact at a strictly later time (use a year-2099 timestamp to make
        # the inequality unambiguous regardless of test machine clock skew)
        compacted_at = "2099-12-31T23:59:59+00:00"
        await store.save_with_compacted_at(
            "web:test",
            session_id="new-sid",
            domain="web",
            token_count=900,
            compacted_at=compacted_at,
        )

        row = await store.get("web:test")
        # Strict inequality: compaction happened AFTER the user's last activity
        assert row["last_compacted_at"] > row["last_active"], (
            f"compacted_at={row['last_compacted_at']!r} should be strictly > "
            f"last_active={row['last_active']!r}"
        )
        # And the actual eligibility check from heartbeat.py:50 uses <=,
        # which trivially holds when strict > does
        assert row["last_active"] <= row["last_compacted_at"]

    @pytest.mark.asyncio
    async def test_replaces_session_id_atomically(self, store):
        """The new method must atomically rotate BOTH session_id AND
        last_compacted_at. A future refactor that splits them back into two
        statements (the v1 race) would re-introduce the crash-recovery loop.
        Asserts the post-state has both fields updated together.
        """
        await store.save("web:test", session_id="orig", domain="web", token_count=5000)
        await store.save_with_compacted_at(
            "web:test",
            session_id="post-compact",
            domain="web",
            token_count=800,
            compacted_at="2026-04-08T03:00:00+00:00",
        )
        row = await store.get("web:test")
        assert row["session_id"] == "post-compact"
        assert row["last_compacted_at"] == "2026-04-08T03:00:00+00:00"
        assert row["token_count"] == 800
        assert row["domain"] == "web"

    @pytest.mark.asyncio
    async def test_raises_keyerror_on_missing_key(self, store):
        """UPDATE on a non-existent row matches zero rows. The method must
        raise KeyError so the caller (nightly_compact) can log + skip when a
        session was deleted between is_compact_eligible() and the post-compact
        DB write (rare race with session.clear() or admin DELETE).
        """
        with pytest.raises(KeyError, match="web:nonexistent"):
            await store.save_with_compacted_at(
                "web:nonexistent",
                session_id="sid",
                domain="web",
                token_count=100,
                compacted_at="2026-04-08T03:00:00+00:00",
            )


class TestNightlyCompactKeyErrorHandling:
    """Verifies nightly_compact catches the KeyError raised by
    save_with_compacted_at and continues to the next eligible session
    instead of crashing the entire loop. Pins the try/except wiring in
    heartbeat.py so a future indentation slip can't silently break it.
    """

    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_nightly_compact_skips_session_deleted_mid_compact(
        self, store, tmp_path, monkeypatch
    ):
        """Two eligible sessions; the first one's save_with_compacted_at
        raises KeyError (simulating deletion mid-compact). nightly_compact
        must catch the error, log a warning, and continue to compact the
        second session. The whole loop must NOT crash.
        """
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        # Seed two eligible sessions
        await store.save("web:deleted", session_id="orig-deleted", domain="web", token_count=5000)
        await store.save("web:survives", session_id="orig-survives", domain="web", token_count=5000)

        # Wrap the real save_with_compacted_at — raise KeyError for the
        # "deleted" key, fall through to the real impl for everything else
        real_save = store.save_with_compacted_at
        save_calls: list[str] = []

        async def raising_save(key, **kwargs):
            save_calls.append(key)
            if key == "web:deleted":
                raise KeyError(f"No session for key {key!r}")
            return await real_save(key, **kwargs)

        store.save_with_compacted_at = raising_save  # type: ignore[method-assign]

        runner = MagicMock()
        runner.workspace = str(workspace)
        # Two /compact calls (one per eligible session) + 1 consolidate = 3 runner.run calls
        compact_a = MagicMock(error=None, session_id="new-a", output_tokens=900)
        compact_b = MagicMock(error=None, session_id="new-b", output_tokens=850)
        consolidate = MagicMock(error=None, session_id=None, output_tokens=10)
        runner.run = AsyncMock(side_effect=[compact_a, compact_b, consolidate])

        # MUST NOT raise — the KeyError on web:deleted must be caught + logged
        await nightly_compact(runner, store, buffer=None)

        # Both keys were attempted (proves the loop didn't bail early)
        assert "web:deleted" in save_calls
        assert "web:survives" in save_calls

        # The surviving session was actually compacted
        survives = await store.get("web:survives")
        assert survives["session_id"] == "new-b" or survives["session_id"] == "new-a", (
            "web:survives should have a rotated session_id (whichever order the loop ran)"
        )
        assert survives["last_compacted_at"] is not None

        # All 3 runner.run calls happened: 2 /compact + 1 consolidate
        assert runner.run.call_count == 3
```

- [ ] **Step 2: Run the new tests to verify they FAIL**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestSessionStoreSaveWithCompactedAt tests/unit/test_nightly_compact.py::TestNightlyCompactKeyErrorHandling -v
```

Expected: 5 tests fail (4 in `TestSessionStoreSaveWithCompactedAt` + 1 in `TestNightlyCompactKeyErrorHandling`). The first 4 fail with `AttributeError: 'SessionStore' object has no attribute 'save_with_compacted_at'`. The 5th (`test_nightly_compact_skips_session_deleted_mid_compact`) fails because `nightly_compact` still calls the old `save()` + `update_compacted_at()` pair, so monkeypatching `save_with_compacted_at` has no effect — the surviving-session assertions will fail.

- [ ] **Step 3: Add the new method to SessionStore**

In `src/raisebull/session.py`, find the existing `save()` method (around line 72-107). Add the new `save_with_compacted_at()` method immediately AFTER `save()`, BEFORE the `clear()` method. Insert this code:

```python
    async def save_with_compacted_at(
        self,
        key: str,
        *,
        session_id: str,
        domain: str,
        token_count: int,
        compacted_at: str,
    ) -> None:
        """Atomic post-compact UPDATE — rotates session_id, refreshes domain
        and token_count, and stamps last_compacted_at in a single SQL
        statement. PRESERVES last_active.

        Used by nightly_compact() to record a successful compact without
        losing the row's user-facing 'last real activity' timestamp.
        last_active is displayed in discord_bot.py:434 ("Last active: ..."),
        webhook_line.py:144, and used as `created_at` in
        admin/routes_chat.py:154 — touching it during a background compact
        would shift those displays to the cron's run time and confuse users.

        Atomicity: a single UPDATE buffered in one transaction. A SIGTERM
        between execute() and commit() leaves the WAL with an uncommitted
        write that's discarded on reopen — so either the old row or the
        new row is visible, never a partial state where session_id rotates
        but last_compacted_at is NULL (the v1 race).

        Raises KeyError if the row doesn't exist (deleted between
        is_compact_eligible() and this call). nightly_compact catches this
        and logs+skips to the next session.
        """
        cursor = await self._require_db().execute(
            """
            UPDATE sessions
            SET session_id = ?, domain = ?, token_count = ?, last_compacted_at = ?
            WHERE key = ?
            """,
            (session_id, domain, token_count, compacted_at, key),
        )
        await self._require_db().commit()
        if cursor.rowcount == 0:
            raise KeyError(f"No session for key {key!r}")
```

- [ ] **Step 4: Run the SessionStore tests to verify they pass**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestSessionStoreSaveWithCompactedAt -v
```

Expected: 4 passed. (`TestNightlyCompactKeyErrorHandling::test_nightly_compact_skips_session_deleted_mid_compact` STILL fails at this point because the wiring change is in Step 5 — that's expected. It will go GREEN after Step 5.)

- [ ] **Step 5: Wire `nightly_compact` to use the new method**

In `src/raisebull/heartbeat.py`, find the per-session compact step (around lines 218-227). The current code is:

```python
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
```

Replace with the atomic UPDATE version. Wraps the call in a `try/except KeyError` because the new method raises if the row was deleted between `is_compact_eligible()` and now (rare race with `session.clear()` or admin DELETE):

```python
            # Step 3: atomic UPDATE of new session_id + last_compacted_at via a
            # single SQL statement. last_active is PRESERVED — it's the user-
            # facing "last real activity" timestamp shown in discord/line/web
            # displays and must not jump to the compact time. KeyError fires
            # if the row was deleted between is_compact_eligible() and now
            # (rare race with session.clear()) — log + skip to next session.
            new_session_id = result.session_id or session_id
            now = datetime.now(timezone.utc).isoformat()
            try:
                await sessions.save_with_compacted_at(
                    key,
                    session_id=new_session_id,
                    domain=s["domain"],
                    token_count=result.output_tokens or s["token_count"],
                    compacted_at=now,
                )
            except KeyError:
                logger.warning(
                    "Nightly compact: %s deleted between eligibility check and "
                    "compact-stamp write — skipping",
                    key,
                )
                continue
```

- [ ] **Step 6: Run the existing nightly_compact tests to verify the wiring**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py -v
```

Expected: ALL nightly_compact tests pass (including `TestNightlyCompactThreshold::test_nightly_compact_uses_threshold_from_settings`, `test_concurrent_runs_serialize_via_lock`, and `TestNightlyCompactLogging::*`). The existing tests use mocked runner.run that returns a result with `output_tokens=900`, so the new `save_with_compacted_at` call gets the same arguments as the old `save()` + `update_compacted_at()` pair, just packed into one method.

Verification checks for backward compatibility:
- `test_nightly_compact_uses_threshold_from_settings` asserts `above["last_compacted_at"] is not None` — the new UPDATE writes this field, assertion holds.
- `test_nightly_compact_uses_threshold_from_settings` asserts `below["last_compacted_at"] is None` — below-threshold session is NEVER passed to save_with_compacted_at (skipped by `is_compact_eligible`), so its row never gets updated. Assertion holds.
- `test_concurrent_runs_serialize_via_lock` asserts `runner.run.call_count == 2` — the refactor packs two DB writes into one but doesn't change the runner.run call count. Assertion holds. The test's comment at line 278 explicitly says "last_active is unchanged" — UPDATE-based fix matches this comment intent (whereas the v2 INSERT OR REPLACE approach would have contradicted it).
- `TestNightlyCompactLogging::*` asserts log format strings — the refactor doesn't touch logging. Assertions hold.

Important semantic note: with the UPDATE-based fix, `above["last_active"]` is preserved as whatever `save()` set it to in the test setup, NOT the compact time. The smoke test `tests/smoke/test_nightly_compact_live.py:201` asserts `above["last_compacted_at"] >= above["last_active"]` — this STILL holds because `last_compacted_at` (set to a later time) is strictly greater than the seeded `last_active`. No existing test asserts that `last_active == compact_time`, so removing that semantic doesn't break anything.

- [ ] **Step 7: Run the full fast suite**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/ --ignore=tests/e2e --ignore=tests/smoke -q
```

Expected: 299 passed (294 from Task 3 + 5 new tests in Task 4: 4 in `TestSessionStoreSaveWithCompactedAt` + 1 in `TestNightlyCompactKeyErrorHandling`). No failures.

- [ ] **Step 8: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add src/raisebull/session.py src/raisebull/heartbeat.py tests/unit/test_nightly_compact.py
git commit -m "$(cat <<'EOF'
fix: atomic compact UPDATE eliminates crash-recovery re-compact loop

Final review (gap analysis) flagged that nightly_compact() did
sessions.save() and sessions.update_compacted_at() as two separate
SQLite commits. A SIGTERM between them leaves the row with a fresh
session_id but last_compacted_at=NULL, so the next cron run treats
it as new activity and re-compacts (cost: 1 wasted Claude call per
crash, plus the row's compaction history is wrong).

Fix: new SessionStore.save_with_compacted_at() does both fields in
ONE atomic SQL UPDATE. The UPDATE-based approach is critical because
it PRESERVES last_active — the user-facing "last real activity"
timestamp displayed in discord_bot.py:434, webhook_line.py:144, and
used as created_at in routes_chat.py:154. An INSERT OR REPLACE would
overwrite last_active with the compact time and shift those user
displays to 03:00 AM after every cron run.

Raises KeyError if the row was deleted between is_compact_eligible()
and the post-compact write (rare race with session.clear() or admin
DELETE). nightly_compact catches it, logs a warning, and skips to
the next session — the compact's /compact Claude call is wasted in
this race window but no DB state is corrupted.

Existing save() and update_compacted_at() methods preserved for
other callers (none today, but cheap insurance).

5 new unit tests cover:
- session_id + last_compacted_at updated, last_active preserved
- last_compacted_at strictly > last_active after compact (the
  d0b8642 invariant from heartbeat.py:50)
- Atomic rotation of session_id + last_compacted_at together
- KeyError on missing row at the SessionStore level
- nightly_compact wiring catches the KeyError and continues to
  the next eligible session (pins the try/except so a future
  indentation slip can't silently break the catch+continue)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Reverse-proxy CLAUDE.md warning

**Files:**
- Modify: `CLAUDE.md` (add warning to the localhost gate Key Decisions bullet)

**Goal:** Document that uvicorn must NOT be run with `--proxy-headers` or `--forwarded-allow-ips` because that would cause `request.client.host` to be derived from `X-Forwarded-For`, allowing external callers to spoof the localhost gate.

- [ ] **Step 1: Update the localhost gate Key Decisions bullet**

In `CLAUDE.md`, find the localhost gate bullet (added in commit `e6dea37` — should be around line 188-189). The current text is:

```markdown
- **Internal endpoints localhost-only** — `/internal/heartbeat/trigger`, `/internal/nightly-compact/trigger`, AND `/internal/discord/push` all reject non-`127.0.0.1`/`::1` callers with 403 via `_require_localhost()`. ASGITransport callers (in tests) leave `request.client` as `None` and are treated as localhost. Future dashboard "Run now" buttons must NOT extend the IP allowlist — instead, add a new `/admin/api/*` route that goes through the existing cookie `auth_middleware` and calls the target function directly. **Known gap:** `routes_settings.py` PUT validation only covers `nightly_compact_threshold`; the other 6 numeric settings (`max_steps`, `auto_reply_timeout`, `session_idle_timeout`, `heartbeat_interval`, `buffer_time`, `nightly_compact_hour`) accept any string and are not server-side validated
```

Replace with (adds the proxy-headers warning paragraph + IPv4-mapped IPv6 note + corrects the ASGITransport client text):

```markdown
- **Internal endpoints localhost-only** — `/internal/heartbeat/trigger`, `/internal/nightly-compact/trigger`, AND `/internal/discord/push` all reject non-loopback callers with 403 via `_require_localhost()`. The gate uses `ipaddress.ip_address(client.host).is_loopback` so it correctly accepts `127.0.0.1`, `::1`, AND `::ffff:127.0.0.1` (IPv4-mapped IPv6, served by some Linux dual-stack uvicorn configs). ASGITransport callers (in tests) default `request.client` to `("127.0.0.1", 123)` in httpx 0.28+, which the loopback check accepts. Future dashboard "Run now" buttons must NOT extend the allowlist — instead, add a new `/admin/api/*` route that goes through the existing cookie `auth_middleware` and calls the target function directly. **⚠️ DO NOT enable uvicorn `--proxy-headers` or `--forwarded-allow-ips`** — those flags make `request.client.host` reflect `X-Forwarded-For` from any header, which lets an external attacker spoof a loopback IP and bypass `_require_localhost()`. Current deployments use raw `--host 127.0.0.1` so safe today, but the warning is here to prevent future regressions. **Known gap:** `routes_settings.py` PUT validation only covers `nightly_compact_threshold`; the other 6 numeric settings (`max_steps`, `auto_reply_timeout`, `session_idle_timeout`, `heartbeat_interval`, `buffer_time`, `nightly_compact_hour`) accept any string and are not server-side validated
```

- [ ] **Step 2: Verify the change is well-formed**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && grep -A 1 "Internal endpoints localhost-only" CLAUDE.md | head -5
```

Expected: shows the new bullet text starting with `- **Internal endpoints localhost-only** — ` and including `⚠️ DO NOT enable uvicorn` somewhere in the body.

- [ ] **Step 3: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: warn against uvicorn --proxy-headers in localhost gate bullet

Final review (Opus) flagged that _require_localhost reads
request.client.host (real socket peer) which is spoof-proof TODAY,
but if anyone enables uvicorn --proxy-headers or --forwarded-allow-ips
later, request.client.host would be derived from X-Forwarded-For —
making the gate trivially bypassable by any header-setting client.

Adds an explicit ⚠️ warning to the localhost gate Key Decisions bullet.
Also folds in the IPv4-mapped IPv6 (::ffff:127.0.0.1) loopback support
note from Task 3, since both relate to the gate semantics.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Edge-case test pinning

**Files:**
- Modify: `tests/unit/test_nightly_compact.py` (extend `TestReadThreshold` and add a new mini-test for output_tokens fallback)

**Goal:** Pin three edge-case behaviors that the code already handles correctly but no test asserts. Without these tests, a future refactor could silently change the behavior.

- [ ] **Step 1: Add the three edge-case tests**

Edit `tests/unit/test_nightly_compact.py`. Find the `TestReadThreshold` class (the one with 12 existing tests). Add these 2 new test methods at the end of that class (after `test_missing_workspace_directory_falls_back_to_default`):

```python
    def test_whitespace_around_value_is_stripped(self, tmp_path, monkeypatch):
        """`_coerce_threshold("  42  ")` (leading/trailing whitespace) → 42.
        Pins the .strip() behavior so a future refactor that drops it would
        silently start rejecting otherwise-valid env values."""
        import json
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "  42  "})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 42

    def test_nested_object_value_falls_through(self, tmp_path, monkeypatch):
        """`_coerce_threshold({"value": 42})` → None (falls through). Pins the
        defensive behavior when settings.json is malformed (e.g., a user
        accidentally writes `{"nightly_compact_threshold": {"value": 42}}`
        instead of `{"nightly_compact_threshold": 42}`). The function must
        NOT crash and must NOT treat the dict as valid."""
        import json
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "8888")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": {"value": 42}})
        )
        from raisebull.heartbeat import _read_threshold
        # Settings.json value is invalid → falls through to env (8888)
        assert _read_threshold(str(tmp_path)) == 8888
```

Then add this third test as a new top-level method on the existing `TestNightlyCompactThreshold` class (where the threshold + lock tests live). Add it AFTER `test_concurrent_runs_serialize_via_lock`:

```python
    @pytest.mark.asyncio
    async def test_compact_with_none_output_tokens_preserves_token_count(
        self, store, tmp_path, monkeypatch
    ):
        """If runner.run('/compact') returns result.output_tokens = None (which
        the runner can do if Claude doesn't report token usage), nightly_compact
        must NOT overwrite the row's token_count with None — it must fall back
        to the original token_count. Pins the `result.output_tokens or s["token_count"]`
        fallback behavior in heartbeat.py.

        IMPORTANT: the test MUST write a settings.json with a low threshold
        (1000) so the 5000-token seeded session IS eligible. Without this, the
        default 50000 threshold would skip the session entirely — runner.run
        would never be called, and the test would falsely "pass" by never
        exercising the fallback path at all.
        """
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        # Low threshold so the 5000-token session qualifies
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        await store.save("web:hot", session_id="orig", domain="web", token_count=5000)

        runner = MagicMock()
        runner.workspace = str(workspace)
        # /compact returns success but with output_tokens=None
        compact_result = MagicMock(error=None, session_id="new-sid", output_tokens=None)
        consolidate_result = MagicMock(error=None, session_id=None, output_tokens=None)
        runner.run = AsyncMock(side_effect=[compact_result, consolidate_result])

        await nightly_compact(runner, store, buffer=None)

        # Sanity: runner.run was actually called — proves the session WAS eligible
        # and the code reached the fallback path (not skipped by is_compact_eligible)
        assert runner.run.call_count == 2  # 1 /compact + 1 consolidate

        row = await store.get("web:hot")
        assert row["session_id"] == "new-sid"  # session was compacted
        # token_count must be the original 5000, NOT None — the fallback path
        # `result.output_tokens or s["token_count"]` evaluates to s["token_count"]
        # because None is falsy.
        assert row["token_count"] == 5000
        assert row["last_compacted_at"] is not None
```

- [ ] **Step 2: Run the new tests**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/test_nightly_compact.py::TestReadThreshold::test_whitespace_around_value_is_stripped tests/unit/test_nightly_compact.py::TestReadThreshold::test_nested_object_value_falls_through tests/unit/test_nightly_compact.py::TestNightlyCompactThreshold::test_compact_with_none_output_tokens_preserves_token_count -v
```

Expected: 3 passed. These tests should pass IMMEDIATELY without any code changes — they're "pinning tests" that lock down existing correct behavior so a future refactor can't silently break it. There is no RED step for these tests.

- [ ] **Step 3: Run the full unit suite**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/unit/ -q
```

Expected: 3 more tests than before (was ~155 unit tests, now ~158). All pass.

- [ ] **Step 4: Run the full fast suite**

Run:

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && .venv/bin/python -m pytest tests/ --ignore=tests/e2e --ignore=tests/smoke -q
```

Expected: 302 passed (299 from Task 4 + 3 from Task 6).

- [ ] **Step 5: Commit**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull
git add tests/unit/test_nightly_compact.py
git commit -m "$(cat <<'EOF'
test: pin three edge-case behaviors that no test exercised

Final review (gap analysis) listed three edge cases the code already
handles correctly but had no test pinning the behavior. A future
refactor could silently change these:

1. _coerce_threshold("  42  ") → 42 — the .strip() call in the parser
   makes whitespace-padded env values work. No test asserted this.

2. _coerce_threshold({"value": 42}) → None — defensive fall-through
   when settings.json has a nested object instead of a scalar. No test
   asserted that the function doesn't crash on dict input.

3. nightly_compact() with result.output_tokens = None — the
   `result.output_tokens or s["token_count"]` fallback at heartbeat.py
   prevents overwriting token_count with None. No test pinned this
   behavior, so a refactor that changed `or` to a more "explicit"
   `if X is not None else Y` could silently regress (the explicit
   form would still work, but a typo could break it).

Three new tests, no code changes — these are pinning tests for
already-correct behavior.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Manual Verification Checklist (after all 6 tasks)

**Workflow principle (NEW):** All verification happens **locally**. The remote `samantha-wsl` `bull-daniu` is the production bot 小牛#8050 — it must NOT be used as a testing ground. Deploy to it only when a feature is ready to ship to users, never for verification.

This is a correction from the nightly_compact feature work, which leaned on the live remote bot for Phase 3 curl + Phase 4 chrome verification. Going forward: prove correctness locally, then ship.

After all tasks land on the branch:

1. **Run the full pre-push hook locally (without actually pushing):**
   ```bash
   cd /Users/pwlee/Documents/Github/raise-a-bull
   .git/hooks/pre-push < /dev/null
   ```
   Expected: 300 fast tests pass (~3s), then the e2e block spawns a local uvicorn fixture on `127.0.0.1:8766`, runs Playwright (~10-30s), tears down. Final exit code 0. **This is the canonical "is the branch ready" check** — no remote needed.

2. **Verify the SKIP_E2E escape hatch works:**
   ```bash
   SKIP_E2E=1 .git/hooks/pre-push < /dev/null
   ```
   Expected: fast tests run, e2e block prints `⚠️  Skipped via SKIP_E2E=1`, exit 0 in ~3s.

3. **Optional: ad-hoc dashboard / curl exploration against a local uvicorn.** If you want to click through the dashboard or curl an endpoint manually, run a local uvicorn instead of touching production:
   ```bash
   cd /Users/pwlee/Documents/Github/raise-a-bull
   # First: make sure :8766 isn't already held by an earlier run
   lsof -ti:8766 && echo "port busy — kill that first" || echo "port free"

   TMP_WS=$(mktemp -d) && mkdir -p "$TMP_WS/config" "$TMP_WS/heartbeat"
   echo '{"nightly_compact_threshold":"50000"}' > "$TMP_WS/config/settings.json"
   echo '## local-dev' > "$TMP_WS/heartbeat/heartbeat.md" && echo '{}' > "$TMP_WS/heartbeat/last-run.json"

   ADMIN_PASSWORD=demo123 LINE_CHANNEL_SECRET=dummy LINE_CHANNEL_ACCESS_TOKEN=dummy \
   DISCORD_BOT_TOKEN= HEARTBEAT_INTERVAL=3600 WORKSPACE="$TMP_WS" \
   DB_PATH="$TMP_WS/sessions.db" CREDENTIALS_DB_PATH="$TMP_WS/credentials.db" \
   .venv/bin/python -m uvicorn raisebull.main:app --host 127.0.0.1 --port 8766
   ```
   Then open `http://127.0.0.1:8766/admin/` and login with `demo123`. Stop with Ctrl-C. Then manually clean the tmpdir (`mktemp -d` does NOT auto-clean — on macOS `/var/folders/...` accumulates until the next reboot, on Linux `/tmp` persists indefinitely):
   ```bash
   rm -rf "$TMP_WS"
   ```
   If you forget this step, the leftover dirs are harmless (~20KB each) but messy — `find /tmp /var/folders -name 'tmp.*' -type d -user $(id -un) -mtime +1 -print` can help audit later.

4. **Push the branch (pre-push runs again as a safety net):**
   ```bash
   git push -u origin cleanup/post-merge-final-review
   ```

5. **Merge to main (clean fast-forward — main never had divergent commits during this work):**
   ```bash
   git checkout main
   git pull
   git merge --ff-only cleanup/post-merge-final-review
   git push origin main
   git branch -d cleanup/post-merge-final-review
   git push origin --delete cleanup/post-merge-final-review
   ```

6. **Production deploy (separate, deliberate step — only when ready to ship to users):**
   The cleanup work in this plan is purely test infrastructure + helper refactors + docs. **It does NOT require a production deploy** because there's no behavior change visible to users. The next time `bull-daniu` rebuilds (for a future feature), it will pick up these improvements automatically.

   If you DO want to deploy now for any reason:
   ```bash
   ssh -p 2222 samantha-machine@samantha-wsl.tail5a1118.ts.net 'cd ~/raise-a-bull && git pull && BOT_NAME=daniu BOT_PORT=18888 WORKSPACE_PATH=/home/samantha-machine/bots/daniu/workspace BOT_ENV_FILE=/home/samantha-machine/bots/daniu/.env docker compose up -d --build'
   ```
   But there is no test or curl step against the remote — production verification = "the bot stays connected and responds to a real user message in the actual Discord/LINE channels". If anything looks broken, roll back via `git revert` on local + redeploy.

---

## Self-Review

**1. Spec coverage:**
- ✅ Tier 1A (root tests in pre-push) → Task 1
- ✅ Tier 1B (IPv4-mapped IPv6) → Task 3
- ✅ Tier 1C (edge case tests) → Task 6
- ✅ Q1 (pre-push playwright, LLM-free subset via SKIP_LLM_E2E) → Task 2
- ✅ Q2 (atomic compact save / SQLite transaction) → Task 4
- ✅ Q3 (settings PUT lost-update) → DEFERRED per brainstorm decision (not in plan, intentional)
- ✅ Q4 (reverse-proxy CLAUDE.md warning) → Task 5

**2. Placeholder scan:** No TBD/TODO/"fill in details". Every step has runnable code or commands. Task 1 Step 4 uses a 4-backtick outer fence so the inner 3-backtick `bash` block renders correctly — the executor copies only what's between the 4-backtick fences.

**3. Type consistency:**
- `save_with_compacted_at(key, *, session_id: str, domain: str, token_count: int, compacted_at: str) -> None` (no `name` parameter — UPDATE only touches the columns we name, so `name` is preserved by SQL semantics, no Python parameter needed). Signature is consistent between Task 4 Step 3 (definition in session.py) and Task 4 Step 5 (caller in heartbeat.py).
- `_require_localhost(request: Request) -> None` signature unchanged — only the body changes in Task 3 (moves `import ipaddress` to top-level and drops the dead `localhost` branch).
- `_coerce_threshold` and `_read_threshold` not modified by this plan.
- Test class names: `TestSessionStoreSaveWithCompactedAt` and `TestNightlyCompactKeyErrorHandling` (Task 4) — both new, no conflict. `TestReadThreshold` and `TestNightlyCompactThreshold` (Task 6) — extending existing classes from the prior feature.
- Pre-push hook env vars: `SKIP_E2E` (bypass entire e2e block) and `SKIP_LLM_E2E` (skip Web Chat + File Upload describes). Both are consistent across the hook, the dashboard.spec.ts skip markers, and the CLAUDE.md doc update.

**4. v3 patches applied after a SECOND round of 3-reviewer review (Opus + Sonnet + Codex):**
- 🟡 **Task 4 last_active semantic regression (Opus catch).** v2's `INSERT OR REPLACE` approach set `last_active = compacted_at`, which would shift the user-facing "Last active: ..." displays in `discord_bot.py:434`, `webhook_line.py:144`, and the `created_at` field in `routes_chat.py:154` to the cron's 03:00 AM run time. **Fixed in v3:** rewrote `save_with_compacted_at` to use a single SQL `UPDATE` (instead of `INSERT OR REPLACE`) that touches only `session_id`, `domain`, `token_count`, `last_compacted_at` — preserving `last_active`. Atomicity preserved (UPDATE is one statement, buffered with commit). Added KeyError on missing-row to catch the rare deleted-mid-compact race; `nightly_compact()` catches it and skips. Sanity-checked against all production readers and tests of `last_active` — no regressions.
- 🟢 **Task 3 commit message contradicted implementation (Codex + Sonnet catch).** v2's commit message still said `"localhost"` branch was "kept as defensive fallback" but the v2 code removed it. **Fixed:** rewrote the commit message to mention the dead-branch removal explicitly.
- 🟢 **Task 2 Step 1 prose said "beforeAll" + "after beforeEach" (Sonnet catch).** Code was correct (`test.skip` placed BEFORE `test.beforeEach`) but the description was misleading. **Fixed:** prose now says "at the TOP of the describe body, BEFORE `test.beforeEach`" and removes the wrong `beforeAll` reference.
- 🟢 **Task 2 cleanup verification `ls /tmp | grep tmp.` unreliable on macOS (Codex catch).** macOS uses `/var/folders/...` for mktemp. **Fixed:** simplified the cleanup check to focus only on `lsof -ti:8766` (the high-value uvicorn-port leak check). Tmpdir leak is acknowledged as cosmetic-only since the trap calls `rm -rf "$TMP_WS"`.
- 🟢 **Task 1 missing `mkdir -p scripts/git-hooks` (Opus catch).** **Fixed:** added an explicit `mkdir -p` instruction in Step 1.
- ❌ **Codex's `\x27` BSD sed claim (rejected).** Codex said macOS BSD sed doesn't support `\x27` escapes. Sonnet contradicted, claiming it works. Verified locally on Darwin 25.2.0: `\x27` IS supported (verified with the exact target line from `dashboard.spec.ts`). Sed command kept as-is, with a comment in Task 2 Step 5 explaining the verification.

**5. v2 patches applied after 3-reviewer review (Opus + Sonnet + Codex):**
- 🔴 **Task 4 timestamp ordering** — Both Codex and Sonnet caught that the original plan captured `last_active` inside the new method AFTER the caller captured `compacted_at`, which inverted the invariant (`last_active > compacted_at`). Fixed: new method sets `last_active = compacted_at` (uses the caller-supplied timestamp for both fields). The semantic meaning "just-compacted row's most recent activity IS the compact" is correct and the invariant `last_compacted_at >= last_active` holds trivially via equality.
- 🔴 **Task 2 cleanup race** — Both Codex and Opus caught that `set -e` would abort before the manual cleanup code ran on a failed playwright invocation, leaking uvicorn + tmpdir. Fixed: `trap cleanup EXIT INT TERM` installed BEFORE the uvicorn spawn + `set +e`/`set -e` brackets around `npx playwright test` so the exit code can be captured for a user-friendly error message.
- 🔴 **Task 2 e2e LLM scoping** — Opus caught that running all e2e tests would spawn real `claude` CLI subprocesses for Web Chat + File Upload describes, adding 60-180s per push and costing real tokens. Fixed: added `test.skip(process.env.SKIP_LLM_E2E === '1', ...)` markers to the Web Chat and File Upload describes (10 tests auto-skip); hook sets `SKIP_LLM_E2E=1`. Pre-push runs the 9 LLM-free tests (Auth + Navigation + Status + Settings) in ~5-15s. Full e2e still available via `npx playwright test` manually.
- 🔴 **Task 2 port collision** — Both Codex and Opus caught that hardcoded port 8766 with no pre-check could run playwright against a stale uvicorn. Fixed: `lsof -ti:8766` pre-check that bails with a clear error + recovery instructions.
- 🔴 **Task 6 None-output-tokens test** — Sonnet caught that the test seeded a 5000-token session but used the default 50000 threshold, so the session was ineligible and the test passed for the wrong reason (zero compacts). Fixed: write `settings.json` with `nightly_compact_threshold=1000` + add `assert runner.run.call_count == 2` sanity check to prove the fallback path was actually exercised.
- 🟡 **Task 3 import placement + dead branch** — Both Opus and Sonnet flagged `import ipaddress` inside the function body as unidiomatic (21 top-level imports in main.py vs ~0 inline imports). Fixed: moved to top-level. Also removed the dead `if client.host == "localhost"` branch that Starlette never exercises.
- 🟡 **Plan + CLAUDE.md ASGITransport text** — Codex caught that the text claimed "ASGITransport leaves request.client as None" but httpx 0.28+ actually defaults to `("127.0.0.1", 123)`. Tests pass (still a loopback IP) but the reasoning was wrong. Fixed: corrected the wording in Task 3 docstring AND in Task 5 CLAUDE.md replacement.
- 🟢 **Task 1 dead branch + install.sh pre-commit reference** — Cosmetic: removed the `if [ $? -ne 0 ]` dead branch under `set -e`, restructured install.sh loop to use a single explicit `HOOKS` variable without the missing `pre-commit` reference.
- 🟢 **Manual verification mktemp cleanup** — Added explicit `rm -rf "$TMP_WS"` instruction (mktemp doesn't auto-clean).
- 🟢 **Task 1 Step 4 escaped backticks** — Restructured to use a 4-backtick outer fence so the inner 3-backtick bash block renders correctly.
- ❌ **Codex's IPv4-mapped IPv6 claim was WRONG** — Codex ran against macOS system Python 3.9 where `is_loopback` doesn't recognize `::ffff:127.0.0.1`. Verified locally on the project's pinned Python 3.14: `is_loopback` DOES handle it correctly. Task 3's original approach is valid.
