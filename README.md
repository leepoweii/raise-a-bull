# raise-a-bull

> **raise-a-bull** — Open-source personal AI operating system, built around Claude Code.

*Previously an OpenClaw feed pack. Pivoted 2026-03-18 to a Claude Code–native framework.*

---

## What is raise-a-bull?

raise-a-bull is a framework for running a personal AI assistant bot that:

- Responds to **LINE** and **Discord** messages
- Uses **Claude Code** (`claude -p`) as the only supported runtime (intentional)
- Persists sessions and memory across restarts
- Supports a **skills system** for extensible behavior
- Integrates with **Paperclip** for multi-agent orchestration
- Deploys on your **local machine** or **Zeabur** (one-click)

**Samantha** is the reference/dogfood deployment — if it works for Samantha, it's in the framework.

---

## Philosophy

- Claude Code is the runtime. We build the infrastructure around it.
- `workspace/` is yours — private, never committed to this repo.
- `src/raisebull/` is the framework — public, pip-installable, updatable.
- Non-technical users are first-class citizens.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/leepoweii/raise-a-bull.git
cd raise-a-bull

# 2. Copy workspace template
cp -r workspace.example workspace
# Edit workspace/CLAUDE.md with your bot's personality

# 3. Configure
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, LINE_*, DISCORD_*

# 4. Run
docker compose up -d
```

---

## Repository Structure

```
raise-a-bull/
├── src/raisebull/        # Framework (pip package)
│   ├── runner.py         # BaseRunner + ClaudeRunner
│   ├── sessions.py       # Session persistence (SQLite)
│   ├── webhook_line.py   # LINE webhook handler
│   ├── webhook_discord.py# Discord bot handler
│   └── heartbeat.py      # Proactive push (APScheduler)
├── workspace/            # Template — copy this, keep private
│   ├── CLAUDE.md         # Bot personality & instructions
│   ├── skills/           # Skill files loaded by claude -p
│   └── memory/           # Persistent memory files
├── docs/                 # Architecture & guides
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

---

## Deployment Options

| Option | Best for | Notes |
|--------|----------|-------|
| Local machine | Power users | Needs Cloudflare tunnel for webhooks |
| Zeabur | Non-tech users | One-click, handles webhooks automatically |

---

## Requirements

- **Claude Code** (`npm install -g @anthropic-ai/claude-code`) — required, intentional
- Docker
- LINE Messaging API account (for LINE bot)
- Discord bot token (for Discord bot)

---

## Samantha as Reference Deployment

Samantha is the dogfood deployment of raise-a-bull. All framework features are battle-tested through Samantha before release. When Samantha upgrades, raise-a-bull upgrades.

---

*raise-a-bull v0.1.0 — Claude Code era begins*
