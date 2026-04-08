# CLAUDE.md — raise-a-bull

## What is this?

raise-a-bull is a **personal AI bot engine** built on Claude Code CLI.
Deploy once — your bot lives in LINE + Discord, knows your context, remembers across conversations.

**Engine + Context = Bot.** The repo is the engine. Each instance is a workspace directory.

---

## Quick Context

### Architecture

```
main.py (single process, asyncio.gather)
├── FastAPI :8000
│   ├── GET  /health
│   ├── POST /webhook/line       ← LINE signature verify → background task
│   ├── POST /internal/discord/push
│   ├── POST /internal/heartbeat/trigger
│   └── /admin/* (dashboard sub-app)
│       ├── Auth (HMAC cookie)
│       ├── Status / Settings / Models / Credentials
│       ├── Context / Skills / Heartbeat editors
│       ├── Permissions (Discord role mapping)
│       └── Web Chat (session CRUD + SSE streaming)
├── Discord Bot (asyncio.create_task)
│   └── Three-tier response (silent → active → timeout)
└── Heartbeat (APScheduler)
    └── Reads heartbeat.md → runs Claude → pushes to Discord/LINE
```

### Tech Stack

| Component | Tech |
|-----------|------|
| LLM | Claude Code CLI (supports MiniMax M2.7 via proxy) |
| HTTP | FastAPI |
| Channels | Discord + LINE + Web Chat |
| MCP Search | minimax_search (Serper Google SERP + Jina Reader) |
| Multimodal | Parsers (text/doc/PDF/XLSX/PPTX) + Gemini Vision + QR/Invoice |
| Dashboard | FastAPI + Alpine.js (neo-brutalism CSS) |
| Database | SQLite (sessions, credentials) |
| Deploy | Docker Compose |

### Source Structure

```
src/raisebull/
├── main.py              — Entry point (FastAPI + Discord + Heartbeat)
├── runner.py            — ClaudeRunner (claude -p subprocess + MCP config)
├── session.py           — SessionStore (SQLite)
├── discord_bot.py       — Discord three-tier response + thread traces
├── webhook_line.py      — LINE webhook (signature + reply/push fallback)
├── heartbeat.py         — APScheduler + heartbeat.md parser
├── stream_buffer.py     — SSE streaming buffer
├── trace.py             — TraceStep parser (thinking/tool_call/tool_result)
├── setup_rich_menu.py   — LINE Rich Menu setup
├── parsers/             — Multimodal attachment parsers
│   ├── text.py          — Plain text + CSV → text
│   ├── document.py      — PDF, DOCX, XLSX, PPTX → markdown
│   ├── vision.py        — Image → Gemini Vision → text description
│   ├── invoice.py       — Taiwan e-invoice QR AES decryption
│   ├── qrcode.py        — QR code scanning + dispatch
│   └── router.py        — MIME classify → parse → save workspace/uploads/
└── admin/               — Dashboard (9 pages)
    ├── auth.py, crud.py, credentials_db.py
    ├── routes_*.py      — 9 route modules (status, chat, context, skills...)
    └── static/          — Alpine.js SPA (index.html + app.js + pages/)
```

### workspace.example/ (new instance template)

```
workspace.example/
├── CLAUDE.md              ← System prompt entry (@includes identity/)
├── AGENTS.md              ← Behavior rules, memory system, group chat etiquette
├── SOUL.md                ← Agent identity template (personality, tone)
├── TOOLS.md               ← Infrastructure notes, date/time helpers
├── HEARTBEAT.md           ← Empty (user adds scheduled tasks)
├── USER.md                ← Human profile template
├── IDENTITY.md            ← Seed (compiled by identity-update skill)
├── bull.json              ← Instance metadata
├── params.json            ← Brand/weather/calendar defaults
├── managed-state.json     ← Skill tracking
├── brand/identity.md      ← Brand identity placeholder
├── config/                ← settings.json, models.json, permissions.json
├── heartbeat/             ← heartbeat.md + last-run.json
├── identity/
│   ├── managed/           ← facts.md, tone.md, local-context.md (templates)
│   └── local/             ← Instance-specific (user fills in)
├── skills/
│   ├── managed/ (8)       ← calendar, document, follow-up, identity-update,
│   │                        inbox, knowledge, meeting, weather
│   ├── generate-image/    ← HTML → Screenshot → image
│   ├── ig-story-design/   ← IG templates (7 HTML + guide)
│   ├── user-memory/       ← Per-member memory on compact
│   └── local/             ← User's custom skills
└── memory/                ← Runtime (created by agent)
```

---

## Docker

```
Dockerfile
├── python:3.12-slim + Node.js 20 + Claude Code CLI
├── uv sync --no-dev
├── pip install minimax_search (MCP server from GitHub)
└── entrypoint.sh
    ├── Bootstrap Claude credentials (base64 → .credentials.json)
    ├── Generate settings.json (env vars + mcpServers if SERPER_API_KEY set)
    └── Seed workspace from workspace.example/ if empty
```

### Docker Compose

```yaml
# Parameterized: BOT_NAME, BOT_PORT, WORKSPACE_PATH, BOT_ENV_FILE
docker compose up -d  # with env vars or .env file
```

### Volumes

- `${WORKSPACE_PATH}:/app/workspace` — persistent, user-editable
- `bot-claude:/home/bull/.claude` — Claude Code config (named volume)

---

## Tests

```bash
# Fast tests (unit + integration, no LLM, ~1s)
uv run pytest tests/unit/ tests/integration/ -q

# Smoke tests (real Claude CLI + MiniMax API, ~60s)
ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic \
ANTHROPIC_AUTH_TOKEN=<key> \
SERPER_API_KEY=<key> \
MINIMAX_API_KEY=<key> \
JINA_API_KEY=<key> \
uv run pytest tests/smoke/ -v

# E2E tests (Playwright, browser)
npx playwright test
```

### Test Structure

```
tests/
├── unit/           — 12 files (trace, heartbeat, stream_buffer, three_tier,
│                     parsers_text, parsers_document, invoice, attachment_router,
│                     buffer, line_mention, nightly_compact, settings_form)
├── integration/    — 7 files (admin, chat, status, attachments, buffer_flow,
│                     history, line_webhook)
├── smoke/          — 3 files (test_smoke + heartbeat_live + nightly_compact_live)
├── e2e/            — Playwright (19 tests: auth, nav, status, settings, chat,
│                     file upload, +3 new Settings drift/round-trip/toast)
└── root            — 5 files (runner, session, discord_bot, main, recovery)
Total: 293 fast + 16 smoke + 19 e2e
```

### Git Hooks

Local pre-push hook lives at `scripts/git-hooks/pre-push` (tracked) and runs the full fast test suite (293 tests, ~3s) before allowing a push. Install after clone with:

```bash
./scripts/git-hooks/install.sh
```

The hook also auto-runs the LLM-free Playwright e2e subset (~5-15s) — it spawns a temporary uvicorn fixture on 127.0.0.1:8766 (with a port-collision pre-check), runs `SKIP_LLM_E2E=1 npx playwright test`, and tears down via a shell trap so cleanup runs even on test failure. The Web Chat + File Upload describes (10 tests) auto-skip via SKIP_LLM_E2E because they need a real authenticated `claude` CLI and cost real tokens — run them manually with `npx playwright test --grep "Web Chat|File Upload"`. Escape hatches: `SKIP_E2E=1 git push` skips the e2e block entirely, `git push --no-verify` skips the whole hook. Use sparingly — the hook caught real bugs (fill('abc') Playwright crash, threshold validation regressions) during the nightly_compact feature work.

---

## Key Decisions

- **Single process** — `asyncio.gather` runs FastAPI + Discord bot + Heartbeat together
- **ClaudeRunner** — wraps `claude -p --output-format stream-json` as async subprocess
- **MCP via --mcp-config** — `claude -p` doesn't auto-read settings.json mcpServers; runner extracts them into mcp.json and passes via `--mcp-config` flag
- **minimax_search** — Serper (Google SERP) + Jina (full page reading) + MiniMax LLM (summarization); 402 errors are swallowed by MCP server (returns generic "empty" message)
- **workspace.example** — fully templatized, zero instance-specific content; new instances seed from here
- **Dashboard auth** — ADMIN_PASSWORD env var → HMAC cookie (httponly, 24hr)
- **LINE webhook** — `asyncio.create_task` for background processing, reply_token → push fallback
- **Multimodal parsers** — attachments parsed → text saved to `workspace/uploads/{session_id}/` → prompt gives path → Claude Code Read tool accesses on demand
- **Vision graceful degrade** — no GEMINI_API_KEY → images get QR scan only, skip description; no pyzbar → skip QR scan
- **Web Chat file upload** — multipart/form-data on same endpoint (backward compatible with JSON), file picker + drag-and-drop + preview bar, 10MB limit, max 5 files
- **Message buffer** — Discord/LINE accumulate messages in SQLite during silent mode; on @mention (Discord) or prefix trigger (LINE), buffer is injected as three-segment prompt (datetime + earlier + recent + mention), then hard-deleted after reply
- **Per-channel lock** — `asyncio.Lock` per channel serializes LLM calls, preventing race conditions
- **Session history** — Dashboard reads Claude Code `.jsonl` files to display full conversation history
- **Heartbeat fresh start** — Each tick uses `session_id=None` to prevent token accumulation
- **Nightly compact** — Scheduled job compacts sessions over the configured token threshold (default 50000) with new activity since the last compact, then runs a single consolidate prompt to update memory files. Skips `heartbeat:*` sessions
- **Nightly compact threshold runtime-configurable** — `nightly_compact_threshold` in `settings.json` (highest priority) or `NIGHTLY_COMPACT_THRESHOLD` env (middle) or hardcoded 50000 default. Each cron tick + each manual trigger re-reads via `_read_threshold()` so dashboard edits take effect without restart. Invalid (zero/negative/non-numeric) values are rejected at PUT-time by the dashboard with HTTP 400, eliminating dashboard ↔ runtime divergence
- **Nightly compact serialized** — Module-level `asyncio.Lock` (`_nightly_lock` in `heartbeat.py`) prevents cron + manual trigger from running `nightly_compact()` concurrently. APScheduler `max_instances=1` only protects the same job_id, not the manual `asyncio.create_task()` path from `/internal/nightly-compact/trigger`
- **Internal endpoints localhost-only** — `/internal/heartbeat/trigger`, `/internal/nightly-compact/trigger`, AND `/internal/discord/push` all reject non-loopback callers with 403 via `_require_localhost()`. The gate uses `ipaddress.ip_address(client.host).is_loopback` so it correctly accepts `127.0.0.1`, `::1`, AND `::ffff:127.0.0.1` (IPv4-mapped IPv6, served by some Linux dual-stack uvicorn configs). ASGITransport callers (in tests) default `request.client` to `("127.0.0.1", 123)` in httpx 0.28+, which the loopback check accepts. Future dashboard "Run now" buttons must NOT extend the allowlist — instead, add a new `/admin/api/*` route that goes through the existing cookie `auth_middleware` and calls the target function directly. **⚠️ DO NOT enable uvicorn `--proxy-headers` or `--forwarded-allow-ips`** — those flags make `request.client.host` reflect `X-Forwarded-For` from any header, which lets an external attacker spoof a loopback IP and bypass `_require_localhost()`. Current deployments use raw `--host 127.0.0.1` so safe today, but the warning is here to prevent future regressions
- **Settings PUT numeric validation** — `routes_settings.py` validates ALL 7 numeric settings via a single `_NUMERIC_CONSTRAINTS` table: `max_steps` / `auto_reply_timeout` / `session_idle_timeout` / `nightly_compact_threshold` (positive int, `> 0`), `heartbeat_interval` / `buffer_time` (non-negative int, `>= 0` so 0 means "disable"), `nightly_compact_hour` (integer 0-23 inclusive). Each rejection returns a canonical `{key} must be {description}` error so clients can match on a single format. Without this, garbage values would be displayed by GET while runtime consumers silently fall back to defaults — the dashboard ↔ runtime divergence class of bug

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_NAME` | ✅ | Container name suffix (`bull-{BOT_NAME}`) |
| `BOT_PORT` | ✅ | Host port (e.g. `18888`) |
| `WORKSPACE_PATH` | ✅ | Absolute host path to `workspace/` |
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | LINE Developers console |
| `LINE_CHANNEL_SECRET` | ✅ | LINE Developers console |
| `CLAUDE_CREDENTIALS` | ✅ | base64 of `~/.claude/.credentials.json` |
| `ADMIN_PASSWORD` | ✅ | Dashboard login password |
| `DISCORD_BOT_TOKEN` | optional | Skip if LINE only |
| `MINIMAX_API_KEY` | optional | MiniMax M2.7 instead of Claude |
| `CLAUDE_MODEL` | optional | Default: `claude-sonnet-4-6` |
| `NIGHTLY_COMPACT_THRESHOLD` | optional | Token threshold for nightly compact (default `50000`). Overridden by `nightly_compact_threshold` in `settings.json` if present |
| `LOG_LEVEL` | optional | Application logger level (default `INFO`). Set `WARNING` or `ERROR` to suppress chatty INFO output. Affects the `raisebull.*` logger family — does not change uvicorn's own loggers |
| `SERPER_API_KEY` | optional | Enables MCP search (free: serper.dev/signup) |
| `JINA_API_KEY` | optional | Enables MCP browse (free: jina.ai) |
| `GEMINI_API_KEY` | optional | Enables image vision (free: aistudio.google.com/apikey) |
