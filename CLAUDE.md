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
├── unit/           — 8 files (trace, heartbeat, stream_buffer, three_tier,
│                     parsers_text, parsers_document, invoice, attachment_router)
├── integration/    — 4 files (admin, chat, status, attachments)
├── smoke/          — 2 files (LLM basic + MCP search + attachment parse/read)
├── e2e/            — Playwright (11 dashboard tests)
└── root            — 5 files (runner, session, discord_bot, main, recovery)
Total: ~130 fast + 12 smoke + 11 e2e
```

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
| `SERPER_API_KEY` | optional | Enables MCP search (free: serper.dev/signup) |
| `JINA_API_KEY` | optional | Enables MCP browse (free: jina.ai) |
| `GEMINI_API_KEY` | optional | Enables image vision (free: aistudio.google.com/apikey) |
