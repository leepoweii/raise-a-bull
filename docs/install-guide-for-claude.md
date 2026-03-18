---
name: raise-a-bull-install
description: Use when helping a user install and set up raise-a-bull — a Claude Code bot framework for LINE and Discord. Guides the full installation from prerequisites to first successful bot response.
---

# raise-a-bull Installation Guide

## Overview

You are guiding a user through installing raise-a-bull so they end up with a working personal AI bot on LINE and/or Discord. Work interactively — run checks, wait for their outputs, catch problems before moving to the next step. Never skip a verification.

**Core principle:** One step at a time. Confirm each step works before continuing.

---

## Phase 1 — Prerequisites

Ask the user to run each check. Wait for their output before continuing.

```bash
# 1. Docker
docker --version        # Need 24+
docker compose version  # Need v2 (not v1 docker-compose)

# 2. Git
git --version

# 3. Claude Code CLI
claude --version        # Need 2.x+

# 4. Claude Code is authenticated
claude -p "say hi" --output-format stream-json 2>&1 | head -3
# Must show {"type":"system",...} — if it prompts for login, stop and help them log in first
```

**If Claude Code isn't installed:**
```bash
npm install -g @anthropic-ai/claude-code
claude   # follow the login flow
```

**Stop if any prerequisite fails.** Don't proceed until all four pass.

---

## Phase 2 — Clone & Configure

```bash
git clone https://github.com/leepoweii/raise-a-bull.git
cd raise-a-bull

# Copy templates
cp .env.example .env
cp -r workspace.example workspace
```

Open `.env` in their editor. You'll fill it in section by section in Phase 3 and 4.

---

## Phase 3 — LINE Bot Setup

Tell the user: *"Go to https://developers.line.biz and sign in. We'll create a Messaging API channel."*

Walk them through these steps **one at a time**, waiting for confirmation at each:

1. **Create a Provider** (if they don't have one) → Providers → Create
2. **Create a Channel** → Create a new channel → Messaging API
3. Fill in: Channel name (e.g. "Callie"), category, description → Agree → Create
4. Go to the **Messaging API** tab
5. **Channel Secret** → Basic Settings tab → copy `Channel secret` → paste into `.env` as `LINE_CHANNEL_SECRET`
6. **Channel Access Token** → Messaging API tab → scroll to "Channel access token" → Issue → copy → paste into `.env` as `LINE_CHANNEL_ACCESS_TOKEN`
7. **Your LINE User ID** → Basic Settings tab → scroll to "Your user ID" → copy → paste into `.env` as `LINE_USER_ID`
8. **Disable auto-reply** → Messaging API tab → LINE Official Account features → Auto-reply messages → Edit → turn OFF
9. **Disable greeting message** → same page → Greeting messages → turn OFF

Leave the browser tab open — you'll need it again in Phase 5 to set the webhook URL.

---

## Phase 4 — Discord Bot Setup (optional)

If the user wants Discord, walk them through:

1. Go to https://discord.com/developers/applications → New Application → name it
2. **Bot** tab → Add Bot → Reset Token → copy → paste into `.env` as `DISCORD_BOT_TOKEN`
3. Enable **Message Content Intent** on the Bot tab (required for reading messages)
4. **OAuth2** tab → URL Generator → scopes: `bot`, `applications.commands` → bot permissions: `Send Messages`, `Read Message History` → copy the generated URL
5. Open the URL in a browser → select your server → Authorize
6. Get your **Guild (Server) ID**: right-click your server name in Discord → Copy Server ID → paste into `.env` as `DISCORD_GUILD_ID`

If they only want LINE, they can leave the Discord vars empty.

---

## Phase 5 — Set WORKSPACE path and Start

```bash
# Get the absolute path to the workspace directory
pwd   # shows current directory — workspace is inside here
```

In `.env`, set `WORKSPACE` to the absolute path:
```
WORKSPACE=/home/yourname/raise-a-bull/workspace
```

Start the container:
```bash
docker compose up -d
```

Wait ~15 seconds, then check it's healthy:
```bash
docker logs raise-a-bull-daniu-1 --tail 20
curl http://localhost:8000/health
# Should return: {"status":"ok","version":"0.1.0"}
```

**If it fails:** check logs carefully. Most common causes:
- Missing required env var (`LINE_CHANNEL_SECRET` or `LINE_CHANNEL_ACCESS_TOKEN`)
- Wrong `WORKSPACE` path (must be absolute, directory must exist)
- Port 8000 already in use (change in docker-compose.yml)

---

## Phase 6 — Expose Webhook (Cloudflare Tunnel)

The bot needs a public HTTPS URL. Cloudflare Tunnel is free and works without port-forwarding.

```bash
# Install cloudflared (Mac)
brew install cloudflare/cloudflare/cloudflared

# Install cloudflared (Linux)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared && sudo mv cloudflared /usr/local/bin/

# Start a temporary tunnel
cloudflared tunnel --url http://localhost:8000
```

Copy the printed `https://xxxx.trycloudflare.com` URL.

Go back to the LINE Developers Console → Messaging API tab → Webhook settings:
1. Paste `https://xxxx.trycloudflare.com/webhook/line` as the Webhook URL
2. Toggle **Use webhook** ON
3. Click **Verify** → should show "Success"

**Note:** The `trycloudflare.com` URL changes every restart. For a permanent URL, set up a named tunnel (ask if they want help with that).

---

## Phase 7 — Verify

1. Open LINE, find the bot by its Basic ID (shown in LINE Developers Console → Basic Settings → Bot basic ID, starts with `@`)
2. Add it as a friend
3. Send "hi"
4. The bot should respond within 10–30 seconds

Check logs while waiting:
```bash
docker logs raise-a-bull-daniu-1 --tail 30 -f
# You should see: POST /webhook/line 200 OK
```

**If no response after 30 seconds:**
- Check the docker logs for errors
- Verify webhook URL is correct and Verify returned Success
- Make sure cloudflared tunnel is still running

---

## Phase 8 — Personalize

```bash
# Edit bot personality
$EDITOR workspace/CLAUDE.md
```

Change the name, tone, language, and instructions freely. The bot will use the new personality on the next message — no restart needed.

---

## Common Errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `LINE_CHANNEL_SECRET must be set` | Empty env var | Check `.env` file |
| Webhook Verify fails | Wrong URL or container not running | Check `curl localhost:8000/health` |
| Bot gets `⚠️ exit 1` | Stale session | Send another message — auto-recovers |
| Bot says "(no response)" | Claude invocation error | Check `docker logs` for details |
| Discord bot not appearing | Missing Message Content Intent | Enable on Discord Developer Portal |

