# Future Improvements

Lessons from onboarding test (2026-03-19). Implement when ready.

---

## 1. Cloudflare Tunnel Setup in Install Guide

**Problem:** `build_barn.sh` installs cloudflared, but the install guide doesn't cover tunnel configuration. The user had to figure out creating tunnels, adding hostnames to config, and routing DNS on their own.

**What to add:**
- Phase in install guide for tunnel setup (not just "choose quick or named")
- For named tunnels: `cloudflared tunnel create`, add hostname to `~/.cloudflared/config.yml`, `cloudflared tunnel route dns`
- Detect existing config and offer to add a new hostname entry
- For quick tunnels: clear instructions that URL changes on restart

---

## 2. Web Search API as MCP Tool

**Problem:** MiniMax model can't use Claude's built-in WebSearch (server-side Anthropic feature). Bots on MiniMax lose web search capability entirely.

**Solution:** Add an optional web search MCP server so any model can search the web.

**Options:**
- [Tavily MCP](https://github.com/tavily-ai/tavily-mcp) — dedicated search API
- [Serper](https://serper.dev/) — Google SERP API
- Custom MCP wrapper around any search provider

**Implementation ideas:**
- Optional `--search-api=tavily` flag in `raise_bull.sh`
- Collect API key via gum, write to `.env`
- Configure MCP server in container's Claude settings (`/home/bull/.claude/settings.json`)
- Or bake a default search MCP into the Docker image

---

## 3. Full TUI Startup (gum-based interactive setup)

**Problem:** Current onboarding requires Claude Code to orchestrate. Works well but adds a dependency on Claude Code being available and understanding the guide.

**Idea:** A standalone `setup.sh` using gum for the entire flow — no Claude Code needed for onboarding.

**Flow:**
```
$ bash setup.sh
? Project name: ox
? Bot name: oxy
? Port [18888]:
? Tunnel type: (named / quick)
? Tunnel domain: oxy.pwlee.xyz
? Enable Discord? (y/N)
? Enable MiniMax? (y/N)

Installing dependencies... ✓
Cloning engine... ✓
Enter secrets below (paste into terminal):
? LINE Channel Secret: ********
? LINE Access Token: ********
? LINE User ID (optional):
? MiniMax API Key: ********

Writing .env... ✓
Starting container... ✓
Waiting for health... ✓

✓ Bot running at https://oxy.pwlee.xyz/webhook/line
```

**Benefits:**
- Works without Claude Code subscription
- Single command, no back-and-forth
- Can still offer Claude Code guide as an alternative for users who want hand-holding

**Considerations:**
- Keeps `raise_bull.sh` and `build_barn.sh` as the backend — TUI is a wrapper
- LINE/Discord/Cloudflare console steps still need the user to do manually (show instructions via gum)
- Could use `gum confirm`, `gum choose`, `gum spin` for polished UX

---

## 4. Bot Skills & Tools Ecosystem

**Goal:** Build a library of skills and tools that bots can load from their workspace.

**What this means:**
- Skills = Claude Code skill documents (markdown prompts the bot can `@include`)
- Tools = MCP servers or bash scripts the bot can invoke

**Examples of useful skills:**
- `/remember` — structured memory management
- `/schedule` — set up recurring heartbeat messages
- `/search` — web search (wraps MCP tool from item #2)
- `/summarize-chat` — summarize recent LINE conversation history
- `/image` — generate or fetch images via agents-infra

**Examples of useful tools:**
- Calendar/reminder MCP
- File upload/download via agents-gateway
- Translation service
- Weather/news API wrapper

**Implementation:**
- Skills live in `workspace/skills/` per bot instance
- Shared skills can live in `engine/skills/` and get copied on seed
- Tools configured as MCP servers in the container's Claude settings
- `raise_bull.sh` could offer `--skills=search,image` to pre-install

---

## 5. agents-infra as Backend Services for Bots

**What exists:** `agents-infra` on samantha-wsl (GitHub: `leepoweii/agents-infra`, private) provides shared Docker services:
- `agents-gateway` (port 18892) — FastAPI: CDN upload, static file serving, screenshot proxy
- `agents-screenshot` (internal) — Playwright/Chromium HTML→image
- Public at `cdn.pwlee.xyz` via Cloudflare tunnel
- All services on `agents-net` Docker bridge network

**How bots can use it:**
- Bots already join `agents-net` — they can reach `agents-gateway` by container name
- Upload images, take screenshots, serve static files — all without external APIs
- Future: add more backend services (e.g. vector DB, cron scheduler, notification queue)

**Implementation plan:**
1. **Phase 1 — Direct HTTP calls (no auth):**
   - Add `GATEWAY_URL` env var to bot `.env` (e.g. `http://agents-gateway:18892` on same network, or `https://cdn.pwlee.xyz` for remote bots)
   - Bot skills/tools call gateway endpoints directly
   - Works now for same-network bots on samantha-wsl

2. **Phase 2 — API key auth:**
   - Add API key middleware to agents-gateway
   - `raise_bull.sh` collects gateway API key via gum
   - Enables remote bots (not on samantha-wsl) to call gateway securely

3. **Phase 3 — Expand services:**
   - Vector DB for bot memory search (RAG)
   - Cron/scheduler service for recurring tasks
   - Notification queue (push messages, email)
   - Shared knowledge base across bots

**Architecture:**
```
Bot (any machine)
  → agents-gateway (cdn.pwlee.xyz or agents-net)
    → agents-screenshot (internal)
    → future: vector-db, scheduler, etc.
```

---

## 6. Audit Logs

**What exists today:** Nothing structured. raise-a-bull has Python `logger.info(...)` lines, uvicorn HTTP access logs, and Claude Code `.jsonl` conversation history — but **no "who did what when" trail** for security/ops forensics.

**What's missing:**
- Who logged into the dashboard (success/fail attempts)
- Who changed which setting (key, old value → new value)
- Who triggered a manual `/internal/heartbeat/trigger` or `/internal/nightly-compact/trigger`
- Who deleted a session via `DELETE /admin/api/chat/{id}`
- Source IP of each action (already available via `request.client.host` after the localhost-gate work)

**Why this matters:**
- **Security forensics:** if a Discord channel suddenly receives a weird message, you want to know whether it came from a real user or `/internal/discord/push` being called (and from where).
- **Settings drift debugging:** "why is `nightly_compact_threshold` at 9999 instead of 50000?" → audit log shows `2026-04-08 03:42 admin (192.168.1.5) changed nightly_compact_threshold: 50000 → 9999`.
- **Accountability:** distinguishes user actions from cron jobs from manual triggers in logs.

**Sizing options:**

**Option B (recommended starting point):** Lightweight audit log
- New SQLite table `audit_log(id, ts, actor, action, target, before, after, source_ip)` in `sessions.db`
- New `src/raisebull/audit.py` module with a single `record(...)` helper
- Hook into:
  - `admin/auth.py` login_endpoint (success + fail, actor=`admin`/`unknown`, source_ip from request.client)
  - `admin/routes_settings.py` PUT (action=`settings.put`, target=key, before=old value, after=new value)
  - `admin/routes_chat.py` DELETE (action=`session.delete`, target=session_id)
  - `main.py` `/internal/*` triggers (action=`internal.heartbeat`/`internal.nightly_compact`/`internal.discord_push`, source_ip)
- ~3-5 hours, ~5 commits with TDD
- No dashboard UI yet — just `sqlite3 sessions.db "SELECT * FROM audit_log ORDER BY ts DESC LIMIT 50"` for querying

**Option C (deferred):** Full audit framework
- Pluggable backend (SQLite + optional file export to JSONL)
- Retention policy (auto-prune after N days)
- Dashboard "Audit log" page with search/filter/redaction for sensitive fields
- Multi-day scope, only worth doing if there's a real compliance need

**Recommendation:** Do Option B in a dedicated session after the current `feat/settings-validation-and-ops-logging` branch ships. Defer Option C until there's an actual compliance/audit requirement.

**Tracked from session 2026-04-08** during the post-merge cleanup work — flagged when reviewing what raise-a-bull has vs. doesn't have for ops observability.

**UPDATE 2026-04-08 (later same day):** Option B shipped on `feat/audit-logs` and merged to main (HEAD `1644c4f`). Scope was expanded during brainstorming to include a dashboard viewer page (B+): server-side date range filter + client-side category filter with 11 action types across 5 groups (Auth / Dashboard / Internal / Scheduler / LINE). 28 new tests (6 unit + 17 integration + 3 scheduler + 2 e2e). Live verification via curl + Chrome confirmed all hook points record correctly, including `scheduler.*` from APScheduler cron path and `_heartbeat_push_impl` Discord push. Option C (retention, export, redaction UI, actor/IP filter) still deferred — see item 7 below.

---

## 7. Audit Logs — Option C follow-ups

**What exists after Option B+ (feat/audit-logs merged):** 11 action types recorded in `sessions.db` `audit_log` table, GET `/admin/api/audit?from=&to=&limit=`, dashboard Audit page with date + category filter, ~28 tests.

**What's still missing (deferred from the original spec's §2 Non-Goals and from code review during implementation):**

### 7a. Retention policy
- **Problem:** `audit_log` grows unbounded. A busy bot could accumulate thousands of rows per month (scheduler.heartbeat fires every N minutes).
- **Fix options:**
  - Auto-prune rows older than N days (configurable in settings.json, e.g. `audit_retention_days=90`) as part of `nightly_compact()`
  - Hard cap on row count (e.g. keep last 100_000 rows, DELETE oldest by `ts`)
- **Scope:** ~2 tests + 1 settings key + 5 lines in `nightly_compact`. Half a session.
- **When to do:** when a production bot's `audit_log` table exceeds ~50k rows.

### 7b. Actor / IP filter on dashboard + API
- **Problem:** Current `GET /admin/api/audit` only supports `from/to/limit`. The dashboard filter is client-side only for action category. Forensics questions like "show me every action from 192.168.1.5" or "what did admin do last week" require `sqlite3` CLI.
- **Fix:** Add `actor=` and `source_ip=` query params to `routes_audit.py`, plus a free-text search box on the dashboard page.
- **Scope:** ~4 tests + ~30 lines. One session.

### 7c. Multi-backend export
- **Problem:** If you want to pipe audit events into an external SIEM (Grafana Loki, Splunk, etc.), you currently need to read the SQLite file directly.
- **Fix options:**
  - Optional JSONL file mirror: every `record()` call also appends to `audit_log.jsonl`
  - Syslog output via Python `logging.handlers.SysLogHandler`
  - HTTP webhook per event (configurable target URL)
- **Scope:** Pluggable `AuditLog` backend interface. ~1 session.
- **When to do:** only if there's a real external monitoring integration requirement.

### 7d. Credentials PUT hook (with redaction)
- **Problem:** The most security-relevant action — changing an API key via `/admin/api/credentials` — is NOT currently audited. It was explicitly out of scope for Option B because recording `before_val`/`after_val` of a credential would itself leak the credential.
- **Fix:** Record a `credentials.put` event with `target=key_name`, `before_val=NULL`, `after_val="<redacted>"` (or a masked suffix like `***abc1`). Never log the actual value.
- **Scope:** ~3 tests + ~10 lines in `routes_credentials.py`. Half a session.
- **Priority:** HIGH — this is the most common "who stole my key" forensics question and it's currently invisible.

### 7e. LINE reply content audit
- **Problem:** Option B deliberately skipped per-message LINE reply logging as "too noisy" since Claude Code `.jsonl` has full dialog. But `.jsonl` is scoped per session — cross-session forensics ("what did the bot say to everyone about topic X this week") isn't possible without parsing every file.
- **Fix (if ever needed):** A separate `line_reply_log` table OR an opt-in `audit.line_reply` action with a truncated message field. Needs scoping — this is high volume.
- **When to do:** only if a real support/review use case emerges.

---

## 8. Production deploy — rebuild bull-daniu on samantha-wsl

**Context:** `feat/audit-logs` + the chat history fix are now on `main`, but production (`bull-daniu` on samantha-wsl) is still on an older commit.

**What to do:**
1. SSH to samantha-wsl: `ssh -p 2222 samantha-machine@samantha-wsl.tail5a1118.ts.net`
2. `cd ~/bull-daniu && git pull origin main && docker compose up -d --build`
3. First startup will auto-add the `audit_log` table via `CREATE TABLE IF NOT EXISTS` — no manual migration needed
4. Verify by logging into the dashboard and navigating to the new Audit page
5. Watch for any regression in existing endpoints (settings, chat, heartbeat)

**Smoke test post-deploy:**
- `curl https://bull.pwlee.xyz/health`
- Log into dashboard, change any setting, refresh Audit page, confirm the `settings.put` row appears
- Check that heartbeat ticks (if enabled) produce `scheduler.heartbeat` rows

**Rollback plan:** the audit_log table is additive, so rolling back the deploy is just `git reset --hard <old-sha> && docker compose up -d --build`. The orphaned table stays but does no harm.

---

## 9. Pre-existing bugs surfaced during audit log code review

Code reviewer flagged these during the feat/audit-logs review pass. All were ruled out-of-scope for that branch but deserve their own fix.

### 9a. Discord task shutdown race (MEDIUM)
- **Problem:** `main.py` lifespan fires `asyncio.create_task(_discord_task())` as a pure fire-and-forget. In shutdown, `_audit_log.close()` and `_sessions.close()` are awaited, but if the Discord task is in the middle of handling a message when shutdown starts, it may call `_audit_log.record()` or `sessions_store.save()` on a closed connection, raising `RuntimeError("init() has not been awaited")` in the event loop.
- **Fix:** Store the Discord task handle, await `task.cancel()` + `await task` in the shutdown block BEFORE closing the DBs. Same pattern for `_process()` background tasks spawned by `webhook_line`.
- **Scope:** ~5 lines + 1 test. Trivial.
- **Priority:** LOW (low-probability race, but real).

### 9b. `AuditLog.record()` has no try/except — transient DB lock turns 400 into 500
- **Problem:** If SQLite is momentarily locked (unlikely under asyncio but possible under concurrent writes from nightly_compact + heartbeat), `audit_log.record()` raises and the HTTP handler propagates it as an unhandled 500. A `login.fail` attempt could return 500 instead of 401 if the audit write throws.
- **Current design choice:** deliberately NOT wrapped — matches the pattern across all hooks. Audit writes are treated as important enough to fail loudly.
- **Fix options:**
  - (a) Wrap `record()` internally with try/except + `logger.exception(...)` + graceful degradation — audit loss is preferred over API failure
  - (b) Leave as-is but document in CLAUDE.md as an intentional failure mode
- **Scope:** ~5 lines inside `AuditLog.record()` + 1 test. Trivial.
- **Priority:** LOW — aiosqlite under asyncio serializes within a connection, so this only bites if someone adds multi-connection write contention later.

### 9c. Z vs +00:00 ISO format normalization only handles `Z`
- **Problem:** `routes_audit.py` `_normalize_iso()` strips trailing `Z` and appends `+00:00`. It does NOT handle non-UTC offsets like `+08:00` or `-05:00`. If a future client sends `2026-04-08T00:00:00+08:00`, it will be compared as a TEXT string against stored `+00:00` values and return wrong boundary rows.
- **Fix options:**
  - (a) Parse with `datetime.fromisoformat()` and re-emit as UTC `+00:00` at the API boundary
  - (b) Store all timestamps as Unix epoch integers in a separate column (schema migration, overkill)
- **Scope:** ~10 lines + 2 tests. Half an hour.
- **Priority:** LOW — current frontend only sends `Z`, so this is only relevant if a third-party client is added.

### 9d. Frontend and backend ISO format asymmetry
- **Problem:** `routes_audit.py` normalizes `Z` → `+00:00` at the API boundary, but the simpler fix is making the frontend send `+00:00` directly (JavaScript can format it). This would eliminate `_normalize_iso()` entirely and keep one canonical format throughout.
- **Fix:** change `audit.js` `load()` to build ISO strings with explicit `+00:00` suffix instead of `Z`.
- **Scope:** 2 lines in `audit.js`, delete `_normalize_iso`, adjust the 1 test. 15 minutes.
- **Priority:** LOW — cosmetic/technical debt, but pairs naturally with 9c.

---

## 10. MCP screenshot tool does not capture audit page visually

**Context:** During live Chrome verification of the dashboard, `mcp__claude-in-chrome__computer action="screenshot"` returned screenshots with empty content area for the Audit page. The accessibility tree confirmed all elements render correctly, JavaScript DOM queries returned proper bounding rects, and injecting a `position: fixed` red debug marker did not appear in screenshots either. Interactive tests (checkbox click → DOM update) worked fine.

**Diagnosis:** This is a tooling bug in the Claude-in-Chrome MCP server, not a bug in the raise-a-bull audit page. Other dashboard pages screenshot correctly — it seems specific to this page.

**What to do:** Nothing in raise-a-bull. File a bug with the claude-in-chrome MCP server if the issue persists. Our e2e tests (Playwright) work correctly and are the authoritative visual regression suite.

**Tracked from session 2026-04-08** — noted here so future manual verification sessions don't waste time debugging it as a dashboard bug.

---

## 11. Settings page — `nightly_compact_threshold round-trips` e2e is flaky on main

**Context:** During the final verification pass before pushing `feat/audit-logs`, the e2e suite showed one failure in `tests/e2e/dashboard.spec.ts › Settings Page › nightly_compact_threshold round-trips through save button`. Confirmed to also fail on `main` before the branch was created — this is a pre-existing flake, not a regression from audit logs.

**What to do:**
1. Reproduce locally: `SKIP_LLM_E2E=1 npx playwright test --grep "nightly_compact_threshold round-trips"`
2. Identify whether it's a timing issue (toast not yet rendered), a locator ambiguity (multiple matching elements), or a real bug in the save button
3. Fix with minimal scope — don't bundle into unrelated branches

**Scope:** Unknown until reproduced. Probably 1 commit.

**Priority:** LOW — pre-push hook currently lets it through because it's already broken on main. Should be cleaned up before any future settings-related work.

---

## 12. Scope-creep observation — audit log scope grew during brainstorming

**Context:** The original spec for item 6 was Option B (lightweight SQLite audit log, no UI, ~3-5 hours). During brainstorming the scope expanded to include:
- Dashboard viewer page with filters (Option B+)
- Scheduler hooks (`scheduler.heartbeat`, `scheduler.nightly_compact`, `scheduler.discord_push`) — not in original Option B
- LINE signature fail hook
- Z-suffix normalization

Final shipped: ~16 commits, 28 tests, ~1-day effort (vs the spec's "3-5 hours" estimate).

**Lesson for future plans:** When a brainstorm pulls in adjacent features, explicitly check whether they belong in the same branch or should be split. In this case keeping them together was the right call (shared schema, shared DB connection, shared test infrastructure) — but it's worth being explicit about the trade-off.

**Not an action item** — just a retrospective note for future planning sessions.

---

## 13. `openspec/` untracked directory

**Context:** `git status` on the repo has always shown `openspec/` as untracked. Nobody knows what it is.

**What to do:** Investigate. Either `.gitignore` it, delete it, or add it to the repo if it's load-bearing. Trivial but has been bugging everyone for months.

**Scope:** 5 minutes.

**Priority:** LOWEST — purely housekeeping.

---

## Next Session Roadmap

Tracked from **session 2026-04-08** during the post-deploy review of `feat/audit-logs`. Items 7-13 above describe the WHAT; this section organizes them into session-sized chunks with explicit priority tiers so future sessions can grab one and run.

### 🥇 Tier 1 — High value, small scope (~half session each, batchable)

| ID | Item | Maps to | Why |
|----|------|---------|-----|
| **N1** | `credentials.put` audit hook with redaction | item 7d | HIGHEST forensics value (currently invisible "who changed my API key"), trivial scope, no design ambiguity. Record `target=key_name`, `after_val="***<last 4>"`, never log full value. ~3 tests + ~10 lines in `routes_credentials.py`. |
| **N2** | Fix `nightly_compact_threshold round-trips` e2e flake | item 11 | Pre-existing flaky e2e blocks pre-push hook for any future Settings work. Reproduce → identify (timing/locator/real bug) → fix with minimal scope. Unknown effort until reproduced, probably 1 commit. |
| **N3** | `_normalize_iso` symmetry cleanup | items 9c + 9d | Either delete `_normalize_iso` and have `audit.js` send `+00:00` directly, OR extend it via `datetime.fromisoformat()` for arbitrary offsets. ~10 lines + 2 tests. 30 minutes. |

**📌 SCHEDULED FOR NEXT SESSION:** N1 + N2 + N3 in a single session, in that order.

### 🥈 Tier 2 — Higher value, full session each

| ID | Item | Maps to | Why |
|----|------|---------|-----|
| **N4** | Audit log retention policy | item 7a | Auto-prune rows older than `audit_retention_days` (settings.json) inside `nightly_compact()`. Prevents `audit_log` table bloat as bot accumulates events over months. ~1 settings key + ~5 lines + ~3 tests + 1 e2e. |
| **N5** | Audit dashboard — actor + IP filter + free-text search | item 7b | Currently you can only filter by date + category, so "show me everything from this IP" requires `sqlite3` CLI. Adds `actor=` and `source_ip=` query params + search box on the dashboard. ~4 tests + ~30 lines backend + Alpine.js search input. |
| **N6** | Discord task shutdown race fix | item 9a | Real bug — `_discord_task()` is fire-and-forget and can call `_audit_log.record()` after the connection is closed in shutdown. Track task handle, cancel + await before closing DBs in lifespan. ~5 lines + 1 test, but shutdown lifecycle tests are fiddly so budget a full session. |

### 🥉 Tier 3 — Lower priority / longer scope

| ID | Item | Maps to | When to do |
|----|------|---------|-----------|
| **N7** | Audit log multi-backend export (JSONL/syslog/webhook) | item 7c | Only when there's a real external SIEM integration requirement |
| **N8** | LINE reply content audit | item 7e | Only when forensics demand cross-session message visibility |
| **N9** | `AuditLog.record()` try/except wrapping | item 9b | Design choice — defer until a real transient-lock incident in production |
| **N10** | `openspec/` directory cleanup | item 13 | LOWEST — purely housekeeping, 5 minutes |

### 🪪 Production deploy state (as of 2026-04-08)

`bull-daniu` on samantha-wsl was rebuilt and deployed during this session:
- Source: `~/Github/raise-a-bull` pulled to commit `38c2028`
- Container: `bull-daniu` rebuilt via `docker compose up -d --build` from `~/docker/bot-daniu`
- DB: `audit_log` table auto-created via `CREATE TABLE IF NOT EXISTS`, existing 2 sessions preserved
- Backup: `~/docker/bot-daniu/workspace/data/sessions.db.pre-audit-log-deploy` (delete after a week if no rollback needed)
- First production audit row: `(1, 'login.fail', 'unknown', '172.18.0.1')` triggered as smoke test

**No rollback needed.** Production is healthy.

---

**End of file.**
