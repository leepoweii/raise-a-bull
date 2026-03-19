# raise-a-bull

A personal AI bot engine built on Claude Code. Deploy once — your bot lives in LINE and Discord, knows your context, and remembers things across conversations. You own everything: the compute, the data, the personality.

---

## What it is

raise-a-bull is a **generic engine**. The repo contains no bot-specific content.

Each bot instance is a **workspace** — a directory with an identity, memory, and skills. One engine, many instances. Like opening different repos in an IDE.

```
~/raise-a-bull/          ← engine (this repo, shared)
~/bots/
├── work/                ← your work assistant
│   ├── .env
│   └── workspace/
├── personal/            ← your personal assistant
│   ├── .env
│   └── workspace/
└── project-x/           ← a bot for a specific project or client
    ├── .env
    └── workspace/
```

Each workspace is self-contained:

```
workspace/
├── CLAUDE.md            ← entry point (@includes identity/)
├── identity/
│   ├── profile.md       ← who the bot is, personality, tone
│   ├── context.md       ← background about you and your work
│   └── expertise.md     ← what this instance specializes in
├── memory/              ← persistent memory (written by Claude)
├── skills/              ← loadable skill documents
└── data/
    └── sessions.db      ← conversation session cache
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical breakdown.

---

## Requirements

- **Claude Max** (~$20/mo) — or a MiniMax API key (see below)
- **LINE Messaging API** account — free tier
- **Discord** account + bot token — optional, free
- **A Linux machine** — Mac Mini, always-on server, or Zeabur

---

## Quick Start

### Step 1 — Clone the engine

```bash
git clone https://github.com/yourname/raise-a-bull.git
```

### Step 2 — Create your first bot instance

```bash
# Create instance directory
mkdir -p ~/bots/mybot

# Copy the env template
cp ~/raise-a-bull/.env.example ~/bots/mybot/.env

# Seed the workspace
cp -r ~/raise-a-bull/workspace.example/. ~/bots/mybot/workspace/
```

### Step 3 — Fill in your identity

Edit `~/bots/mybot/workspace/identity/profile.md` — give your bot a name and personality.  
Edit `~/bots/mybot/workspace/identity/context.md` — tell it about you.

This is the only content you need to touch.

### Step 4 — Configure secrets

Edit `~/bots/mybot/.env`:

```env
# Compose vars
BOT_NAME=mybot
BOT_PORT=18888
WORKSPACE_PATH=/home/yourname/bots/mybot/workspace

# Container vars
CLAUDE_BIN=claude
CLAUDE_MODEL=claude-sonnet-4-6
WORKSPACE=/app/workspace
DB_PATH=/app/workspace/data/sessions.db

# LINE
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_CHANNEL_SECRET=...
LINE_USER_ID=...

# Discord (optional)
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=

# Claude auth (base64 of ~/.claude/.credentials.json)
CLAUDE_CREDENTIALS=...
```

For a guided walkthrough of LINE and Discord setup, paste [docs/install-guide-for-claude.md](docs/install-guide-for-claude.md) into a Claude conversation.

### Step 5 — Copy the launch helper

```bash
cp ~/raise-a-bull/bots/start-bot.sh ~/bots/start-bot.sh
chmod +x ~/bots/start-bot.sh
```

### Step 6 — Start

```bash
cd ~/bots && bash start-bot.sh mybot
curl http://localhost:18888/health
# {"status":"ok","version":"0.1.0"}
```

### Step 7 — Expose webhook

```bash
cloudflared tunnel --url http://localhost:18888
```

Set the printed URL as your LINE webhook: `https://<tunnel>/webhook/line`

---

## Optional: Use MiniMax instead of Claude subscription

Set two extra vars in your `.env` to use MiniMax M2.7 (~$0.30/$1.20 per M tokens) instead of Claude Max:

```env
MINIMAX_API_KEY=sk-api-...
CLAUDE_MODEL=MiniMax-M2.7
```

The engine writes the necessary config automatically on startup. Get a key at https://platform.minimax.io

---

## Adding more instances

```bash
mkdir -p ~/bots/work
cp ~/raise-a-bull/.env.example ~/bots/work/.env
cp -r ~/raise-a-bull/workspace.example/. ~/bots/work/workspace/
# edit .env (different BOT_NAME and BOT_PORT)
# edit workspace/identity/
bash ~/bots/start-bot.sh work
```

Each instance gets its own port, its own identity, its own memory, and its own session history.

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
| `DISCORD_BOT_TOKEN` | optional | Skip if LINE only |
| `DISCORD_GUILD_ID` | optional | Your Discord server ID |
| `MINIMAX_API_KEY` | optional | Use MiniMax instead of Claude subscription |
| `CLAUDE_MODEL` | optional | Model name (default: `claude-sonnet-4-6`) |

---

## Health check

```bash
curl http://localhost:18888/health
# {"status":"ok","version":"0.1.0"}
```

---

## What this is not

- ❌ Not a hosted service — you own your data and compute
- ❌ Not model-agnostic — Claude Code only, by design
- ❌ Not a no-code tool — you edit `identity/`, that's the minimum
- ❌ Not a replacement for Claude.ai — it's a bot layer, not a chat UI
