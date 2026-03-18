# raise-a-bull

An open-source personal AI operating system built around Claude Code. You deploy it once — your bot (Callie / 小牛) lives in LINE and Discord, knows your context, and remembers things across conversations. You own everything: the compute, the data, the personality.

---

## Requirements

- **Claude Max** (~$20/mo) — required. raise-a-bull runs `claude -p` under the hood; no Claude Max, no bot.
- **LINE Messaging API** account — free tier is enough
- **Discord** account + bot token — free
- **A machine to run it on** — Mac Mini, always-on Linux box, or Zeabur (see below)

**Cost estimate:** Claude Max $20/mo + optional Zeabur ~$5/mo. That's it.

---

## Quick Start

### Option A — Zeabur (recommended for non-developers)

1. Click **Deploy to Zeabur** *(button coming soon)*
2. Fill in your environment variables (see `.env.example`)
3. Add your bot on LINE — say hi

### Option B — Local machine

```bash
# 1. Clone
git clone https://github.com/yourname/raise-a-bull
cd raise-a-bull

# 2. Copy and fill in your keys
cp .env.example .env
$EDITOR .env

# 3. Copy the workspace template
cp -r workspace.example workspace

# 4. Start
docker compose up -d

# 5. Expose webhook (Cloudflare tunnel recommended)
cloudflared tunnel --url http://localhost:8000
```

Set the printed URL as your LINE webhook: `https://<your-tunnel>/webhook/line`

---

## Personalizing your bot

Everything about your bot's personality lives in `workspace/CLAUDE.md`. Open it and edit freely:

```markdown
# Callie / 小牛 — Personality & Instructions

You are Callie (小牛), a personal AI assistant.
...
```

**Want to rename your bot?** Just change the name in `workspace/CLAUDE.md`. The framework doesn't care what you call her.

**Want to add skills?** Drop Markdown files into `workspace/skills/`. Claude reads them on every message.

**Want persistent memory?** Write to `workspace/memory/`. Claude reads it too.

---

## Environment variables

See `.env.example` for the full list. The essentials:

| Variable | Required | Description |
|----------|----------|-------------|
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | From LINE Developers console |
| `LINE_CHANNEL_SECRET` | ✅ | From LINE Developers console |
| `DISCORD_BOT_TOKEN` | optional | Skip if you only want LINE |
| `DISCORD_GUILD_ID` | optional | Your Discord server ID |
| `WORKSPACE` | ✅ | Absolute path to your `workspace/` dir |
| `CLAUDE_BIN` | optional | Path to `claude` binary (default: `claude`) |

---

## Health check

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"0.1.0"}
```

---

## What this is not

- ❌ Not a hosted service — you own your data and compute
- ❌ Not model-agnostic — Claude Code only, by design
- ❌ Not a no-code tool — you edit `CLAUDE.md`, that's the minimum
- ❌ Not a replacement for Claude.ai — it's a bot layer, not a chat UI
