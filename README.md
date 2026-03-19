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

**Prerequisite:** [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated.

Open a terminal in the repo directory and launch Claude Code:

```bash
claude
```

Then reference the install guide:
```
@docs/install-guide-for-claude.md
```

Claude will orchestrate the full setup — installing dependencies, guiding account creation, and starting your bot.

> ⚠️ Keep your LINE/Discord tokens in a local notepad. You will enter them securely in the terminal at the end — never paste secrets into the chat.

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
