# raise-a-bull — Product Requirements Document

**Version:** 0.1  
**Date:** 2026-03-18  
**Status:** Draft  

---

## Problem Statement

Non-technical people can't run a personal AI assistant. Existing solutions are either too technical (self-hosted LLMs), too locked-in (ChatGPT), or too brittle (OpenClaw). Claude Code is powerful but has no "always-on bot" layer around it.

Anyone who can pay for Claude Max should be able to have their own Samantha — a personal AI that lives in LINE/Discord, knows their context, and takes initiative.

---

## Vision

**raise-a-bull** is an open-source personal AI operating system built around Claude Code.

You install it once. Your bot (Callie / 小牛) lives in LINE and Discord. She knows your context, remembers things, proactively reminds you, and can be extended with skills. You own everything.

---

## Default Bot Identity

- **English name:** Callie  
- **Chinese name:** 小牛  
- Users can rename their bot freely in `workspace/CLAUDE.md`

---

## Target Users

| Type | Profile | Deploy path |
|------|---------|-------------|
| **Type A** — Power user | Developer, comfortable with Docker and CLI | Local machine + Cloudflare tunnel |
| **Type B** — Non-tech | Has Claude Max, wants a bot, not a sysadmin | Zeabur one-click template |

---

## The One Hard Requirement

**Claude Code (`claude -p`) is the only supported runtime.**

This is intentional — it's the quality gate. We don't support OpenAI, Gemini, or raw Anthropic API. If you want Callie, you need Claude Code.

---

## Core Concepts

### workspace/
Everything personal lives here. Users copy the template, keep it private. Never committed to the framework repo.

```
workspace/
├── CLAUDE.md       # Bot personality, instructions, identity
├── skills/         # Skill files — loaded by claude -p
└── memory/         # Persistent memory files
```

### Skills system
Skills are Markdown files in `workspace/skills/`. Loaded via `claude -p --add-dir workspace/`. Three loading modes:

| Mode | When loaded |
|------|-------------|
| `always` | Every message |
| `heartbeat` | Heartbeat context only |
| `on-demand` | Triggered by keywords in message |

### Sessions
Each user gets a persistent session ID stored in SQLite. Conversations have memory across restarts.

### Heartbeat
APScheduler runs every 15 minutes. Checks configured sources (calendar, daily note, tasks). Pushes proactive reminders to LINE/Discord. Safety valve: `MAX_DAILY_HEARTBEAT_TRIGGERS` prevents spam loops.

---

## Feature Roadmap

### v1 — MVP (extract from Samantha)

- [ ] LINE webhook handler + loading animation
- [ ] Discord bot handler  
- [ ] `ClaudeRunner` — wraps `claude -p --add-dir workspace/`
- [ ] Session persistence per user (SQLite)
- [ ] `workspace/` template (CLAUDE.md + skills/ + memory/)
- [ ] Docker + docker-compose
- [ ] Zeabur one-click deploy template
- [ ] `.env.example` with all required vars
- [ ] README — setup guide for Type B users

### v2 — Proactive & extensible

- [ ] Heartbeat system (APScheduler, configurable windows, safety valve)
- [ ] Skills loading modes (`always` / `heartbeat` / `on-demand`)
- [ ] Slash commands (`/brief`, `/session-info`, `/new-session`)
- [ ] Cloudflare tunnel auto-setup for local deploy
- [ ] agents-infra integration (screenshot, CDN upload)

### v3 — Orchestration

- [ ] Paperclip integration (`/agent/task` endpoint — Callie becomes a Paperclip agent)
- [ ] Federated bot model (Callie controls other bots via agents-infra API)
- [ ] Context server (FastAPI serving knowledge base, agents self-update memory)
- [ ] Web UI (Tauri or browser-based)

---

## Architecture

```
User (LINE / Discord)
        ↓
  FastAPI webhook
        ↓
  show_loading_animation()    ← immediate feedback (LINE only)
        ↓
  ClaudeRunner.run()
    └─ claude -p --add-dir workspace/ [prompt]
        ↓
  reply to user
  sessions.save()
```

### Runner abstraction

```python
class BaseRunner:
    async def run(self, prompt: str, session_id: str | None) -> RunResult: ...

class ClaudeRunner(BaseRunner):
    # claude -p --add-dir workspace/ [--resume session_id] [prompt]
```

Future runners (Codex, Gemini) implement `BaseRunner`. Callie stays the same.

---

## Deployment Options

| Option | Best for | Webhook URL | Notes |
|--------|----------|-------------|-------|
| Local machine | Type A | Cloudflare tunnel | Recommended — data never leaves your machine |
| Zeabur | Type B | Auto-exposed | One-click, managed |

**Recommended hardware (local):** Mac Mini M4 or any always-on Linux machine.

---

## Pricing Story

Users need:
- **Claude Max** (~$20/mo) — required for `claude -p`
- **LINE Messaging API** — free tier sufficient
- **Discord** — free
- **Zeabur** (optional) — ~$5/mo if cloud deploy

This should be clearly stated in the README upfront.

---

## Multi-user

v1: **single primary user** (matches Samantha's model). The bot knows one person deeply.  
v2: Support family/team (2–5 users, each with their own session, shared workspace).

---

## Samantha = Reference Deployment

Samantha (running on samantha-wsl) is the dogfood deployment of raise-a-bull. All v1 features are already live in Samantha. The raise-a-bull framework is extracted from Samantha's codebase.

When raise-a-bull ships v1, Samantha migrates to `pip install raisebull` and becomes a workspace on top of the framework.

---

## What raise-a-bull is NOT

- ❌ Not a hosted service (you own your data, your compute)
- ❌ Not model-agnostic (Claude Code only, by design)
- ❌ Not a no-code tool (you edit CLAUDE.md — that's the minimum)
- ❌ Not a replacement for Claude.ai (it's a bot layer, not a chat UI)

---

## Success Criteria

A non-technical user (Type B) can:
1. Read the README
2. Click "Deploy to Zeabur"
3. Fill in their API keys
4. Add Callie on LINE
5. Say hi — and get a response

In under 30 minutes, without touching code.
