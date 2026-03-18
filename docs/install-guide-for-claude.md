---
name: raise-a-bull-install
description: Use when helping a user install and set up raise-a-bull — a Claude Code bot framework for LINE and Discord. Guides the full installation from prerequisites to first successful bot response.
---

# raise-a-bull Installation Guide

## Overview

You are guiding a user through installing raise-a-bull so they end up with a working personal AI bot on LINE and/or Discord. Work interactively — run checks, wait for their outputs, catch problems before moving to the next step. Never skip a verification.

**Core principle:** One step at a time. Confirm each step works before continuing.

> **Prerequisites required first.** Before starting, confirm the user has completed `docs/prerequisites-for-claude.md` — accounts (Claude Max, LINE Developer, Cloudflare) and software (Docker, Node, Claude Code CLI, cloudflared) must all be installed and verified. If not, stop and guide them through it first.

---

## Phase 1 — Quick Prerequisites Check

Run the final checklist from `prerequisites-for-claude.md`:

```bash
docker --version        && echo "✓ Docker"
docker compose version  && echo "✓ Docker Compose"
git --version           && echo "✓ Git"
node --version          && echo "✓ Node"
claude --version        && echo "✓ Claude Code CLI"
cloudflared --version   && echo "✓ cloudflared"
claude -p "say hi" --output-format stream-json 2>&1 | grep -q "type" && echo "✓ Claude auth"
```

**All seven must show ✓.** If any fail, stop and fix via `prerequisites-for-claude.md`.

> **PATH note (Linux):** If `claude` is not found after install, add it:
> ```bash
> echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
> ```

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

> **Do not change `CLAUDE_BIN`** — leave it as `claude`. The Docker container already has Claude Code CLI installed at `/usr/bin/claude` and it resolves automatically. Setting it to a path on the host machine will break it.

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
7. **Your LINE User ID** → Basic Settings tab → scroll to "Your user ID" (format: `Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`) → copy → paste into `.env` as `LINE_USER_ID`
   - This is the LINE UID of your own account (the developer account logged into LINE Developers Console)
   - If you can't find it here, skip it for now — see "Finding your LINE_USER_ID" in the Common Errors section
8. **Disable auto-reply** → Messaging API tab → LINE Official Account features → Auto-reply messages → Edit → turn OFF
9. **Disable greeting message** → same page → Greeting messages → turn OFF

Leave the browser tab open — you'll need it again in Phase 6 to set the webhook URL.

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
docker compose logs --tail 20
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

> **⚠️ Named tunnel conflict:** If you already have a Cloudflare named tunnel running (i.e., you ran `cloudflared tunnel run` as a service), the quick tunnel below will return 404 due to the named tunnel's catch-all rule. In that case, add a new ingress rule to your named tunnel's `config.yml` instead of using the quick tunnel command. Ask the user if they have an existing named tunnel before proceeding.

```bash
# Start a temporary tunnel (skip if you have a named tunnel — see note above)
cloudflared tunnel --url http://localhost:8000
```

Copy the printed `https://xxxx.trycloudflare.com` URL.

Go back to the LINE Developers Console → Messaging API tab → Webhook settings:
1. Paste `https://xxxx.trycloudflare.com/webhook/line` as the Webhook URL
   - **The path must be exactly `/webhook/line`** — not `/webhook`
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
docker compose logs --tail 30 -f
# You should see: POST /webhook/line 200 OK
```

**If no response after 30 seconds:**
- Check the docker logs for errors
- Verify webhook URL ends in `/webhook/line` and Verify returned Success
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
| Webhook Verify fails with 404 | Wrong URL path | Make sure URL ends with `/webhook/line`, not `/webhook` |
| Webhook Verify fails with named tunnel | Named tunnel catch-all intercepts quick tunnel | Add ingress rule to named tunnel config instead |
| Bot gets `⚠️ exit 1` | Stale session | Send another message — auto-recovers |
| Bot says "(no response)" | Claude invocation error | Check `docker compose logs` for details |
| Bot receives messages but never replies | `CLAUDE_BIN` set to host path | Set `CLAUDE_BIN=claude` in `.env` (leave as default) |
| Discord bot not appearing | Missing Message Content Intent | Enable on Discord Developer Portal |

### Finding your LINE_USER_ID

If you couldn't find your User ID in the LINE Developers Console:

1. Make sure the bot is running and the webhook is set
2. Add the bot as a friend on LINE and send any message (e.g. "hello")
3. Run: `docker compose logs | grep "user_id\|line:U"`
   - Or look for a line containing `line:Uxxxxxxx` in the logs
4. Copy the `Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` value and paste it into `.env` as `LINE_USER_ID`
5. Restart: `docker compose restart`
