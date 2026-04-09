# raise-a-bull

A personal AI bot engine built on Claude Code. Deploy once — your bot lives in LINE and Discord, knows your context, and remembers things across conversations. You own everything: the compute, the data, the personality.

---

## What it is

raise-a-bull is a **generic engine**. The repo contains no bot-specific content.

Each bot instance is a **workspace** — a directory with an identity, memory, and skills. One engine, many instances. Like opening different repos in an IDE.

```
~/my-bulls/                ← project root (you name it)
├── engine/                ← this repo (shared, upgradeable)
├── work/                  ← your work assistant
│   ├── .env
│   └── workspace/
├── personal/              ← your personal assistant
│   ├── .env
│   └── workspace/
└── project-x/             ← a bot for a specific project or client
    ├── .env
    └── workspace/
```

---

## Features

- **Multi-channel** — Discord + LINE + Web Chat (dashboard), all sharing the same session store
- **Multimodal attachments** — Discord/LINE images, PDFs, DOCX, XLSX, PPTX, CSV parsed into text, saved to workspace, Claude reads on demand via Read tool
- **Image vision** — Gemini Flash describes images (receipts, documents, photos) in Chinese; QR codes auto-decoded including Taiwan e-invoices
- **Dashboard** — Admin panel with status, context editor, skills editor, heartbeat viewer, credentials, permissions, and web chat (Alpine.js SPA, neo-brutalism CSS)
- **MCP Search** — Web search (Google SERP via Serper) + full page reading (Jina Reader), auto-configured when API keys are set
- **Heartbeat** — Scheduled tasks via APScheduler + user-editable `heartbeat.md` (default 60 min interval)
- **Memory** — SQLite session store + per-member memory files + daily digests
- **Token logging** — Per-call LLM token usage logged at INFO level (`LLM call: source=... input=N output=N total=N`) for cost tracking and observability
- **Skills** — 11 prebuilt skills (calendar, document draft, weather, image generation, IG design, etc.) + extensible with custom skills
- **Identity** — Layered identity system (managed templates + local customization → compiled IDENTITY.md)

---

## Requirements

- **Claude Max** (~$20/mo) — or a MiniMax API key (see below)
- **LINE Messaging API** account — free tier
- **Discord** account + bot token — optional, free
- **A Linux machine** — Mac Mini, always-on server, or cloud VM

---

## Quick Start

**Prerequisite:** [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated.

```bash
# 1. Clone and setup
git clone https://github.com/leepoweii/raise-a-bull.git
cd raise-a-bull

# 2. Create your instance
mkdir -p ~/bots/mybot
cp .env.example ~/bots/mybot/.env
cp -r workspace.example/. ~/bots/mybot/workspace/

# 3. Edit .env (add LINE/Discord tokens, set BOT_NAME, BOT_PORT)
# 4. Edit workspace/identity/ (who your bot is)
# 5. Edit workspace/USER.md (who you are)
# 6. Edit workspace/SOUL.md (personality and tone)

# 7. Launch
docker network create agents-net 2>/dev/null
BOT_NAME=mybot BOT_PORT=18888 \
BOT_ENV_FILE=~/bots/mybot/.env \
WORKSPACE_PATH=~/bots/mybot/workspace \
docker compose up -d
```

> ⚠️ Keep your LINE/Discord tokens in a local notepad. Never paste secrets into chat.

---

## Workspace structure

Each instance gets a full workspace seeded from `workspace.example/`:

```
workspace/
├── CLAUDE.md              ← Entry point (@includes identity/)
├── AGENTS.md              ← Behavior rules, memory system, group chat etiquette
├── SOUL.md                ← Personality, tone, memory protocol
├── USER.md                ← About the human owner
├── IDENTITY.md            ← Auto-compiled from identity/managed/ + identity/local/
├── brand/identity.md      ← Brand colors, fonts, logo, social handle
├── config/                ← Agent settings, models, permissions
├── heartbeat/             ← Scheduled task definitions + run tracker
├── identity/
│   ├── managed/           ← Framework-provided templates (facts, tone, local-context)
│   └── local/             ← Your custom identity files
├── skills/
│   ├── managed/ (8)       ← Calendar, document-draft, weather, inbox, etc.
│   ├── generate-image/    ← HTML → Screenshot → image
│   ├── ig-story-design/   ← IG Story/Post templates (7 HTML)
│   ├── user-memory/       ← Per-member memory on compact
│   └── local/             ← Your custom skills
└── memory/                ← Created at runtime by the agent
```

---

## Optional: MiniMax instead of Claude subscription

Set two extra vars in your `.env` to use MiniMax M2.7 (~$0.30/$1.20 per M tokens):

```env
MINIMAX_API_KEY=sk-api-...
CLAUDE_MODEL=MiniMax-M2.7
```

The engine writes the necessary config automatically on startup. Get a key at https://platform.minimax.io

---

## Optional: Web search (MCP)

Add these to your `.env` to enable web search and page reading:

```env
SERPER_API_KEY=...    # Free: https://serper.dev/signup (2,500 searches)
JINA_API_KEY=...      # Free: https://jina.ai (10M tokens)
```

The engine auto-configures the `minimax_search` MCP server on startup. Your bot gets two tools:
- **search** — Google SERP results (batch queries, Chinese-optimized)
- **browse** — Full page content reading via Jina Reader

---

## Optional: Image vision (Gemini)

Add to your `.env` to enable image description for photo attachments:

```env
GEMINI_API_KEY=...    # Free: https://aistudio.google.com/apikey
```

Without this key, images are still processed for QR codes (including Taiwan e-invoices), but no visual description is generated.

---

## Dashboard

Access at `http://localhost:{BOT_PORT}/admin/` (password set via `ADMIN_PASSWORD` env var).

**Pages:** Status, Context Editor, Credentials, Heartbeat, Permissions, Settings, Skills, Chat, Login

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_NAME` | ✅ | Container name suffix (`bull-{BOT_NAME}`) |
| `BOT_PORT` | ✅ | Host port to expose (e.g. `18888`) |
| `WORKSPACE_PATH` | ✅ | Absolute host path to `workspace/` |
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | From LINE Developers console |
| `LINE_CHANNEL_SECRET` | ✅ | From LINE Developers console |
| `CLAUDE_CREDENTIALS` | ✅ | base64 of `~/.claude/.credentials.json` |
| `ADMIN_PASSWORD` | ✅ | Dashboard login password |
| `DISCORD_BOT_TOKEN` | optional | Skip if LINE only |
| `DISCORD_GUILD_ID` | optional | Your Discord server ID |
| `MINIMAX_API_KEY` | optional | Use MiniMax instead of Claude subscription |
| `CLAUDE_MODEL` | optional | Model name (default: `claude-sonnet-4-6`) |
| `NIGHTLY_COMPACT_THRESHOLD` | optional | Token threshold for nightly compact (default `50000`). Editable from the dashboard Settings page without restart |
| `LOG_LEVEL` | optional | Application logger level (default `INFO`). Set `WARNING` to suppress chatty INFO output for privacy-sensitive deployments |
| `HEARTBEAT_INTERVAL` | optional | Heartbeat scheduler interval in seconds (default `3600` = 60 min). Set `0` to disable |
| `SERPER_API_KEY` | optional | Enables MCP web search |
| `JINA_API_KEY` | optional | Enables MCP page reading |
| `GEMINI_API_KEY` | optional | Enables image vision (Gemini Flash) |

---

## Health check

```bash
curl http://localhost:18888/health
# {"status":"ok","version":"0.1.0"}
```

---

## Tests

```bash
# Fast (unit + integration, ~1s)
uv run pytest tests/unit/ tests/integration/ -q

# Smoke (real LLM + MCP, ~60s)
uv run pytest tests/smoke/ -v

# E2E (Playwright, browser)
npx playwright test
```

---

## What this is not

- ❌ Not a hosted service — you own your data and compute
- ❌ Not model-agnostic — Claude Code only, by design
- ❌ Not a no-code tool — you edit `identity/`, that's the minimum
- ❌ Not a replacement for Claude.ai — it's a bot layer, not a chat UI

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical breakdown.
