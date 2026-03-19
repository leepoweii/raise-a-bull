# raise-a-bull Onboarding Design

**Date:** 2026-03-19
**Status:** Approved
**Scope:** build_barn.sh + raise_bull.sh + Claude-orchestrated onboarding flow

---

## Problem

Setting up raise-a-bull requires installing system dependencies, creating accounts on multiple external services, obtaining API secrets, and configuring Docker, Cloudflare, and LINE webhook. Without guidance this is too complex for non-developers. But full automation removes the minimum competency gate that protects users from getting irreversibly stuck.

---

## Design Principles

1. **Claude Code is the entry point** — users must have Claude Code CLI installed and authenticated. This is the minimum competency bar.
2. **Secrets never enter the chat** — Claude explicitly warns users at the start and again before raise_bull.sh to keep tokens in a local notepad. Secrets only enter via gum-secured terminal prompts at the very end.
3. **Parallel setup** — dependency installation (build_barn.sh) and account setup run concurrently via subagent dispatch.
4. **Screenshot guides handle account UX** — Claude references visual guides for external console navigation rather than step-by-step text.

---

## Components

### `docs/install-guide-for-claude.md` (Starter Prompt)

The single entry point. Users paste this into Claude Code. Claude reads it and orchestrates the entire onboarding.

**Must include:**
- Security warning (shown at start AND again before raise_bull.sh):
  > ⚠️ Do NOT paste any tokens, secrets, or API keys into this chat.
  > Store them in a local notepad. You will be guided to enter them securely at the end.
- References to screenshot guides for each external service
- Instruction to dispatch subagent for build_barn.sh
- Collect all non-sensitive config before calling raise_bull.sh
- Final step: call raise_bull.sh with flags — gum handles all secret input

---

### `build_barn.sh`

One-time dependency installer. Called by Claude subagent in background while user sets up accounts.

**Installs (idempotent — skips if already present):**

| Package | macOS | WSL/Linux |
|---------|-------|-----------|
| Docker | brew install --cask docker + open -a Docker + wait for daemon | get.docker.com + usermod -aG docker $USER |
| Node.js | brew install node | nodesource setup_20.x |
| gum | brew install gum | go install / binary release |
| gh | brew install gh (optional) | apt (optional) |
| cloudflared | brew install cloudflared (optional) | .deb binary (optional) |

**macOS Docker special case:**
```bash
open -a Docker
echo "Waiting for Docker daemon..."
until docker info &>/dev/null 2>&1; do sleep 1; done
echo "Docker ready"
```

**Output:** plain checkmarks per package, no interactive prompts, exits non-zero on failure.

---

### `raise_bull.sh <name> [flags]`

Creates a bot instance. Claude calls this after collecting all non-sensitive config.

**Flags (non-sensitive — passed by Claude):**
```
--port=18888
--domain=bot.example.com   # named tunnel domain (omit = quick tunnel)
--minimax                  # enable MiniMax backend
--discord                  # enable Discord
```

**Flow:**
1. Create ~/bots/<name>/workspace/data/ directory
2. Copy workspace.example/ to ~/bots/<name>/workspace/
3. Auto-read ~/.claude/.credentials.json -> CLAUDE_CREDENTIALS
4. gum secure input (only step using gum):
   - LINE Channel Secret (--password)
   - LINE Access Token (--password)
   - LINE User ID
   - Discord Token (--password, only if --discord)
   - MiniMax API Key (--password, only if --minimax)
5. Write ~/bots/<name>/.env with chmod 600
6. bash ~/bots/start-bot.sh <name>
7. Wait for /health, print webhook URL

---

## Account Requirements

| Service | What to obtain | Required? | Notes |
|---------|---------------|-----------|-------|
| Claude Code | (already logged in) | Prerequisite | |
| LINE Developer | Channel Secret, Access Token, User ID | Required | |
| Cloudflare | Named tunnel + domain | Required for production | Quick tunnel OK for testing |
| Discord | Bot Token, Guild ID | Either/or with LINE | Can add later |
| MiniMax | API Key | Team/shared use only | Personal use: Claude subscription |

**LINE vs Discord:** At least one must be enabled. Both can run simultaneously.

**MiniMax:** Required when the bot is shared among multiple users (e.g. group LINE chat with different people). This avoids violating Claude single-account policy. Personal single-user bots can use Claude subscription.

---

## Onboarding Flow

```
User opens terminal
  -> claude (Claude Code CLI)
  -> pastes install-guide-for-claude.md

Claude:
  SECURITY REMINDER (shown immediately):
  "Do NOT paste tokens or secrets here.
   Keep them in a local notepad.
   You will enter them securely at the end."

  -> dispatch subagent: bash build_barn.sh   [runs in background]

  -> guide user through accounts (parallel with build_barn):
      [Screenshot guide] LINE Developer Console
        - Channel Secret    -> notepad
        - Access Token      -> notepad
        - User ID           -> notepad

      [Screenshot guide] Cloudflare Tunnel
        - named tunnel + domain  OR  confirm quick tunnel for now

      [Choice] Discord?
        -> yes: [Screenshot guide] Discord Developer Portal

      [Choice] Team/shared use?
        -> yes: [Screenshot guide] MiniMax platform -> API Key -> notepad

  -> confirm build_barn.sh subagent complete

  SECURITY REMINDER (shown again):
  "About to enter secrets. Your terminal will prompt you.
   Type or paste only into the terminal — not here."

  -> raise_bull.sh mybot --port=18888 --domain=bot.example.com [--discord] [--minimax]
      gum: secure secret input
      writes .env (chmod 600)
      starts container
      prints webhook URL

  -> guide: paste webhook URL into LINE Developer Console
  -> verify: send "hi" to bot
  -> done
```

---

## Security Contract

| Rule | Enforcement |
|------|-------------|
| Secrets never in chat | Claude warns twice; gum --password for all input |
| .env not world-readable | chmod 600 in raise_bull.sh |
| CLAUDE_CREDENTIALS auto-read | Never typed — read from ~/.claude/.credentials.json |
| MiniMax isolated from host | settings.json written by entrypoint.sh in container volume |

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `build_barn.sh` | Create in repo root |
| `raise_bull.sh` | Create in repo root |
| `docs/install-guide-for-claude.md` | Update — security warnings, subagent dispatch, screenshot refs |
| `docs/screenshots/` | Placeholder — LINE, Discord, Cloudflare, MiniMax step-by-step |
| `README.md` | Update Quick Start — Claude Code as entry point |

---

## Out of Scope

- Web UI / landing page
- Automated account creation
- Windows native (WSL only)
- Multi-bot setup in one session (run raise_bull.sh again for additional bots)
