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

## Phase 2 — Clone Engine & Create Instance

raise-a-bull uses a two-layer structure: a shared **engine** repo, and per-bot **instance** directories outside the repo.

```bash
# 1. Clone the engine (shared, never edited per-bot)
git clone https://github.com/leepoweii/raise-a-bull.git

# 2. Create your first bot instance directory
BOT=mybot   # change this to whatever you want to call your bot
mkdir -p ~/bots/$BOT

# 3. Copy env template into instance dir
cp ~/raise-a-bull/.env.example ~/bots/$BOT/.env

# 4. Seed workspace from template
cp -r ~/raise-a-bull/workspace.example/. ~/bots/$BOT/workspace/

# 5. Copy launch helper (one-time)
cp ~/raise-a-bull/bots/start-bot.sh ~/bots/start-bot.sh
chmod +x ~/bots/start-bot.sh
```

Open `~/bots/$BOT/.env` in their editor. You will fill it in section by section in the next phases.

> **Structure note:** The engine repo stays untouched. All bot-specific content lives in `~/bots/<name>/`. This lets you run multiple bots from one engine installation.

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

Leave the browser tab open — you'll need it again in Phase 7 to set the webhook URL.

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

## Phase 4.5 — LLM Backend (optional: MiniMax instead of Claude subscription)

By default the bot calls Claude via the CLI using your Claude subscription. If you want to use **MiniMax M2.7** (Anthropic-API-compatible, ~$0.30/$1.20 per M tokens) instead, set two extra vars in `.env`:

```env
MINIMAX_API_KEY=sk-api-xxxxxxxxxxxxxxxxxxxxxxxx   # your MiniMax API key
CLAUDE_MODEL=MiniMax-M2.7                          # model name passed to --model flag
```

On every container start, `entrypoint.sh` detects `MINIMAX_API_KEY` and writes `/home/bull/.claude/settings.json` with the MiniMax base URL and auth token — completely isolated from your host Claude subscription.

To get a MiniMax API key: https://platform.minimax.io

> **Note:** If `MINIMAX_API_KEY` is not set, the bot uses your normal Claude subscription (no settings.json is written). You do not need this step unless you want a separate billing account for the bot.

---

## Phase 5 — Configure .env and Get Claude Credentials

Open `~/bots/$BOT/.env`. Fill in the compose-level vars at the top:

```env
# Compose-level vars (docker compose uses these for interpolation)
BOT_NAME=mybot              # must match the directory name you chose
BOT_PORT=18888              # pick any unused port
WORKSPACE_PATH=/home/yourname/bots/mybot/workspace   # absolute path
```

Then get your Claude credentials:

```bash
# Encode your Claude credentials as base64
base64 -w 0 ~/.claude/.credentials.json
```

Paste the output into `.env` as `CLAUDE_CREDENTIALS`.

Verify the full `.env` looks like this (with real values):

```env
BOT_NAME=mybot
BOT_PORT=18888
WORKSPACE_PATH=/home/yourname/bots/mybot/workspace

CLAUDE_BIN=claude
CLAUDE_MODEL=claude-sonnet-4-6
WORKSPACE=/app/workspace
DB_PATH=/app/workspace/data/sessions.db
MAX_DAILY_HEARTBEAT_TRIGGERS=20

LINE_CHANNEL_ACCESS_TOKEN=<filled in Phase 3>
LINE_CHANNEL_SECRET=<filled in Phase 3>
LINE_USER_ID=<filled in Phase 3>

DISCORD_BOT_TOKEN=<filled in Phase 4, or leave empty>
DISCORD_GUILD_ID=<filled in Phase 4, or leave empty>

CLAUDE_CREDENTIALS=<base64 string from above>
```

---

## Phase 6 — Personalize Your Bot

Edit the identity files in `~/bots/$BOT/workspace/identity/`:

```bash
$EDITOR ~/bots/$BOT/workspace/identity/profile.md   # who the bot is, name, tone
$EDITOR ~/bots/$BOT/workspace/identity/context.md   # about you and your work
```

`expertise.md` is optional — fill it in if this bot has a specific focus (e.g. customer service for a particular product, or a specialized knowledge domain).

> **This is the only content you need to customize.** Everything else (memory, skills, sessions) is managed automatically.

---

## Phase 7 — Start the Bot

Create the data directory and start:

```bash
mkdir -p ~/bots/$BOT/workspace/data

cd ~/bots && bash start-bot.sh $BOT
```

Wait ~20 seconds (first run builds the Docker image), then check:

```bash
curl http://localhost:18888/health
# {"status":"ok","version":"0.1.0"}
```

Check logs while it starts:

```bash
docker logs bull-$BOT --tail 30
```

Look for:
- `Claude credentials written.` — auth OK
- `MiniMax settings.json written.` — if using MiniMax
- `raise-a-bull startup complete` — app ready

**If it fails:** check logs carefully. Most common causes:
- Missing required env var (`LINE_CHANNEL_SECRET` or `LINE_CHANNEL_ACCESS_TOKEN`)
- Wrong `WORKSPACE_PATH` (must be absolute, directory must exist)
- Port already in use (change `BOT_PORT` in `.env`)
- `CLAUDE_CREDENTIALS` invalid (re-run the base64 encode command)

---

## Phase 8 — Expose Webhook (Cloudflare Tunnel)

The bot needs a public HTTPS URL. Cloudflare Tunnel is free and works without port-forwarding.

> **⚠️ Named tunnel conflict:** If you already have a Cloudflare named tunnel running, the quick tunnel may return 404 due to a catch-all rule. Add a new ingress rule to your named tunnel's `config.yml` instead.

```bash
# Start a temporary tunnel (skip if you have a named tunnel)
cloudflared tunnel --url http://localhost:18888
```

Copy the printed `https://xxxx.trycloudflare.com` URL.

Go back to the LINE Developers Console → Messaging API tab → Webhook settings:
1. Paste `https://xxxx.trycloudflare.com/webhook/line` as the Webhook URL
   - **The path must be exactly `/webhook/line`**
2. Toggle **Use webhook** ON
3. Click **Verify** → should show "Success"

**Note:** The `trycloudflare.com` URL changes every restart. For a permanent URL, set up a named tunnel.

---

## Phase 9 — Verify

1. Open LINE, find the bot by its Basic ID (LINE Developers Console → Basic Settings → Bot basic ID, starts with `@`)
2. Add it as a friend
3. Send "hi"
4. The bot should respond within 10–30 seconds

Check logs while waiting:
```bash
docker logs bull-$BOT --tail 30 -f
# You should see: POST /webhook/line 200 OK
```

---

## Phase 10 — LINE Rich Menu (optional but recommended)

The rich menu adds a persistent button bar at the bottom of the LINE chat with **New Session**, **Session Info**, and **Compact** buttons.

```bash
docker compose -p "bull-$BOT" run --rm bot python -m raisebull.setup_rich_menu
```

After running, send any message to the bot on LINE — the menu bar will appear.

---

## Common Errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `LINE_CHANNEL_SECRET must be set` | Empty env var | Check `.env` file |
| Webhook Verify fails with 404 | Wrong URL path | Make sure URL ends with `/webhook/line` |
| Container exits immediately | Bad `CLAUDE_CREDENTIALS` | Re-encode: `base64 -w 0 ~/.claude/.credentials.json` |
| Bot gets `⚠️ exit 1` | Stale session | Send another message — auto-recovers |
| Bot says "(no response)" | Claude invocation error | Check `docker logs bull-$BOT` |
| Discord bot not appearing | Missing Message Content Intent | Enable on Discord Developer Portal |

### Finding your LINE_USER_ID

If you couldn't find your User ID in the LINE Developers Console:

1. Make sure the bot is running and the webhook is set
2. Add the bot as a friend on LINE and send any message
3. Run: `docker logs bull-$BOT | grep "line:U"`
4. Copy the `Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` value → paste as `LINE_USER_ID`
5. Restart: `cd ~/bots && bash start-bot.sh $BOT`

---

## Adding a Second Bot Instance

```bash
BOT2=work   # or any name

mkdir -p ~/bots/$BOT2
cp ~/raise-a-bull/.env.example ~/bots/$BOT2/.env
cp -r ~/raise-a-bull/workspace.example/. ~/bots/$BOT2/workspace/
mkdir -p ~/bots/$BOT2/workspace/data

# Edit .env: set BOT_NAME=$BOT2, BOT_PORT=18889 (different port!), WORKSPACE_PATH=...
$EDITOR ~/bots/$BOT2/.env

# Edit identity
$EDITOR ~/bots/$BOT2/workspace/identity/profile.md

# Start
bash ~/bots/start-bot.sh $BOT2
```

Each instance runs independently on its own port with its own identity, memory, and session history.
