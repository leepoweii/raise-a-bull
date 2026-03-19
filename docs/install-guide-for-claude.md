---
name: raise-a-bull-install
description: Use when helping a user install and set up raise-a-bull — a Claude Code bot framework for LINE and Discord. Orchestrates full installation from prerequisites to first bot response.
---

# raise-a-bull Installation Guide (Claude Orchestration)

## Your role

You are orchestrating the complete raise-a-bull onboarding. Work interactively — confirm each step before proceeding. You run the technical steps; the user handles web consoles.

> **SECURITY — Show this immediately, before anything else:**
>
> "Do NOT paste any tokens, secrets, or API keys into this chat.
> Store everything in a local notepad as you collect it.
> You will enter secrets securely in the terminal at the very end."

---

## Phase 1 — Name Your Project

Ask the user: **"What do you want to name your project directory?"**

Examples: `my-bulls`, `line-bots`, `samantha-bots`

This creates `~/<project-name>/` with everything inside:
```
~/<project-name>/
├── engine/          ← raise-a-bull repo (shared, upgradeable)
├── <bot-name>/      ← bot instance (per bot)
│   ├── .env
│   └── workspace/
└── <another-bot>/
```

Save the chosen name as `PROJECT_ROOT="$HOME/<project-name>"`.

---

## Phase 2 — Verify Prerequisites

Claude Code is already running (that's how the user opened this guide). Check git:

```bash
git --version && echo "✓ git"
```

If git is missing, ask the user to install it before continuing.

---

## Phase 3 — Install Dependencies (background subagent)

Create the project directory, clone the engine, and dispatch a subagent to run `build_barn.sh` while you guide account setup in parallel.

```bash
mkdir -p "$PROJECT_ROOT"

# Clone engine repo if not already present
if [ ! -d "$PROJECT_ROOT/engine" ]; then
  git clone https://github.com/leepoweii/raise-a-bull.git "$PROJECT_ROOT/engine"
fi
```

Dispatch a **background subagent** to run:
```bash
bash "$PROJECT_ROOT/engine/build_barn.sh"
```

Tell the user: "I'm installing dependencies in the background — this takes a few minutes. While that runs, let's set up your accounts."

---

## Phase 4 — LINE Bot Setup

Tell the user to go to https://developers.line.biz and sign in.

Guide them one step at a time, waiting for confirmation at each:

1. Create a Provider (if none exists) → Providers → Create
2. Create a Channel → Messaging API → fill in name, category, description → Create
3. **Channel Secret** → Basic Settings tab → copy `Channel secret` → save to notepad
4. **Channel Access Token** → Messaging API tab → scroll to "Channel access token" → Issue → copy → save to notepad
5. **LINE User ID** → Basic Settings tab → scroll to "Your user ID" (format: `Uxxxxxxxxx`) → copy → save to notepad
   - If not visible, skip for now (recoverable from logs after first message)
6. **Disable auto-reply** → Messaging API tab → LINE Official Account features → Auto-reply → Edit → OFF
7. **Disable greeting** → same page → Greeting messages → OFF

Leave this browser tab open — you'll paste the webhook URL here in Phase 11.

*Reference: docs/screenshots/line/ (guides coming soon)*

---

## Phase 5 — Cloudflare Tunnel (choose one)

Ask the user:

> "Do you want a permanent webhook URL (named tunnel) or a temporary one (quick tunnel — changes on restart)?"

**Option A — Quick tunnel (easier, good for testing):**
No setup needed now. You'll start it in Phase 11 with one command.

**Option B — Named tunnel (production):**
Ask the user for their tunnel domain (e.g. `bot.example.com`). They need a Cloudflare account with a domain and the tunnel configured. Record the domain for Phase 9.

*Reference: docs/screenshots/cloudflare/ (guides coming soon)*

---

## Phase 6 — Discord (optional)

Ask: "Do you want Discord support in addition to LINE?"

If yes, guide them through https://discord.com/developers/applications:

1. New Application → name it
2. Bot tab → Add Bot → Reset Token → copy → save to notepad as Discord Token
3. Enable **Message Content Intent** (Bot tab)
4. OAuth2 → URL Generator → scopes: `bot`, `applications.commands` → permissions: `Send Messages`, `Read Message History` → copy generated URL → open in browser → authorize to their server
5. Right-click server name in Discord → Copy Server ID → save to notepad as Discord Guild ID

*Reference: docs/screenshots/discord/ (guides coming soon)*

---

## Phase 7 — MiniMax (optional — shared/team use only)

Ask: "Will this bot be shared among multiple users (e.g. a group LINE chat with different people)?"

If yes, MiniMax is required (avoids violating Claude single-account policy):
Guide them to https://platform.minimax.io → get API key → save to notepad.

If no (personal single-user bot): skip this phase.

*Reference: docs/screenshots/minimax/ (guides coming soon)*

---

## Phase 8 — Confirm build_barn.sh Complete

Check that the background subagent from Phase 3 has finished. Verify:

```bash
docker --version      && echo "✓ Docker"
docker info           && echo "✓ Docker daemon"
node --version        && echo "✓ Node"
gum --version         && echo "✓ gum"
cloudflared --version && echo "✓ cloudflared"
```

All must show ✓. If any fail, run `bash "$PROJECT_ROOT/engine/build_barn.sh"` directly and wait.

---

## Phase 9 — Create Bot Instance

Collect from the user (non-sensitive — ask in chat):
- Bot name (e.g. `mybot`)
- Port (default: `18888`)
- Tunnel domain from Phase 5, or none (quick tunnel)
- Whether to enable Discord (from Phase 6)
- Whether to enable MiniMax (from Phase 7)

> **SECURITY REMINDER — Show this again before running raise_bull.sh:**
>
> "About to enter secrets. Your terminal will prompt you for each key.
> Type or paste ONLY into the terminal prompts — not here in chat."

Build the command based on what you collected and run it. For example:

```bash
# Always include --port and --root. Add --domain only if they have a named tunnel.
# Add --discord only if Phase 6 was completed. Add --minimax only if Phase 7 was completed.
bash "$PROJECT_ROOT/engine/raise_bull.sh" mybot --port=18888 --root="$PROJECT_ROOT"

# With named tunnel: add --domain=bot.example.com
# With Discord:      add --discord
# With MiniMax:      add --minimax
```

The script will:
- Seed `$PROJECT_ROOT/mybot/workspace/` from the template
- Prompt for all secrets in the terminal (not in chat)
- Write `$PROJECT_ROOT/mybot/.env` (chmod 600)
- Start the Docker container
- Wait for /health and print the webhook URL

---

## Phase 10 — Personalize Bot Identity

After raise_bull.sh completes, open the identity files:

```bash
$EDITOR $PROJECT_ROOT/mybot/workspace/identity/profile.md   # bot name, personality, tone
$EDITOR $PROJECT_ROOT/mybot/workspace/identity/context.md   # about the owner
```

`expertise.md` is optional — fill in if the bot has a specialized focus.

---

## Phase 11 — Set Webhook URL

**If using quick tunnel** — run this in a separate terminal (keep it running):
```bash
cloudflared tunnel --url http://localhost:18888
```
Copy the `https://xxxx.trycloudflare.com` URL.

**If using named tunnel** — webhook URL is `https://your-domain.com`.

Go to LINE Developers Console → Messaging API tab → Webhook settings:
1. Paste `https://<your-url>/webhook/line` — path must be exactly `/webhook/line`
2. Toggle **Use webhook** ON
3. Click **Verify** → should show "Success"

---

## Phase 12 — Verify

1. Open LINE → find the bot by Basic ID (Basic Settings → Bot basic ID, starts with `@`) → Add as friend
2. Send "hi"
3. Bot should respond within 10–30 seconds

Check logs while waiting (replace `mybot` with the bot name you chose in Phase 9):
```bash
docker logs bull-mybot --tail 30 -f
```

---

## Common Errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `LINE_CHANNEL_SECRET must be set` | Empty env var | Re-run raise_bull.sh |
| Webhook Verify fails 404 | Wrong URL path | URL must end with `/webhook/line` |
| Container exits immediately | Bad `CLAUDE_CREDENTIALS` | Check credentials and re-run raise_bull.sh |
| Bot says "(no response)" | Claude invocation error | Check `docker logs bull-mybot` |
| Discord bot offline | Missing Message Content Intent | Enable on Discord Developer Portal |
| `network agents-net not found` | Docker network missing | Run `docker network create agents-net` then retry |

### Finding LINE_USER_ID from logs

If you skipped LINE User ID in Phase 4:
1. Make sure bot is running and webhook is set
2. Add bot on LINE and send any message
3. Run: `docker logs bull-mybot | grep "line:U"`
4. Copy the `Uxxxxxxxxxxxxxxxx` value → edit `$PROJECT_ROOT/mybot/.env` → restart: `bash "$PROJECT_ROOT/engine/bots/start-bot.sh" mybot --root="$PROJECT_ROOT"`

---

## Adding a Second Bot

Run raise_bull.sh again with a different name and port:

```bash
bash "$PROJECT_ROOT/engine/raise_bull.sh" workbot --port=18889 --root="$PROJECT_ROOT"
# Add --discord / --minimax as needed
```

Each instance runs independently on its own port with its own workspace and identity.

---

## Upgrading the Engine

To pull the latest engine code and restart a bot:

```bash
bash "$PROJECT_ROOT/engine/bots/upgrade_bull.sh" mybot --root="$PROJECT_ROOT"
```

This runs `git pull` in `engine/` and restarts the container. Your workspace, identity, and sessions are untouched.
