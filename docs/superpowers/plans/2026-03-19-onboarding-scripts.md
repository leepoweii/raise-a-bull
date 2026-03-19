# Onboarding Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `build_barn.sh` (idempotent dependency installer via Homebrew) and `raise_bull.sh` (bot instance creator with gum-secured secret input), then update `docs/install-guide-for-claude.md` to use Claude Code as the orchestration entry point.

**Architecture:** Both scripts live in the repo root. `build_barn.sh` uses Homebrew on both macOS and WSL/Linux (Linuxbrew) — one install path, no OS branching except for the Docker cask on macOS. `raise_bull.sh` collects non-sensitive config as flags, then uses `gum input --password` for all secrets, and writes `~/bots/<name>/.env` (chmod 600). The install guide is a Claude Code starter prompt — users paste it into Claude Code and Claude orchestrates the rest.

**Tech Stack:** bash, Homebrew (brew.sh), gum (charmbracelet/gum), Docker, cloudflared

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `build_barn.sh` | Create | Idempotent dependency installer; Homebrew-first on macOS + WSL |
| `raise_bull.sh` | Create | Bot instance creator: dirs, .env, gum secrets, start container |
| `bots/start-bot.sh` | Add to repo | Launch helper (exists on samantha-wsl, not committed yet) |
| `bots/upgrade_bull.sh` | Create | Engine upgrade script: `git pull` + restart, context untouched |
| `docs/install-guide-for-claude.md` | Rewrite | Claude Code starter prompt — orchestrates full onboarding |
| `docs/screenshots/.gitkeep` | Create | Placeholder directory for future screenshot guides |

---

## Task 1: `build_barn.sh`

**Files:**
- Create: `build_barn.sh`

Context: This script runs once as a Claude subagent in the background while the user sets up accounts. It must be idempotent (safe to run twice), non-interactive (no prompts), and exit non-zero on failure. Both macOS and WSL use Homebrew. The only platform split is Docker: macOS gets `--cask docker` (Docker Desktop) + daemon wait; WSL gets `brew install docker` (CLI only — Docker Desktop for Windows with WSL integration provides the daemon).

One critical fix in the Docker block: installation check (cask present?) and daemon readiness check (daemon running?) are separate concerns and must be handled separately. The `brew_install` helper is only for installation; daemon startup is always checked/triggered independently.

Also: `build_barn.sh` creates the `agents-net` Docker network if it doesn't exist, because `docker-compose.yml` declares it as `external: true` — if missing, `docker compose up` silently fails.

- [ ] **Step 1: Create `build_barn.sh`**

```bash
cat > build_barn.sh << 'SCRIPT'
#!/usr/bin/env bash
# build_barn.sh — Idempotent dependency installer for raise-a-bull
# Usage: bash build_barn.sh
# Called by Claude subagent during onboarding. No interactive prompts.
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}" >&2; exit 1; }

detect_platform() {
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "macos"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
    else
        fail "Unsupported platform. Supported: macOS, WSL/Linux"
    fi
}

PLATFORM=$(detect_platform)
echo "Platform: $PLATFORM"

# ── 1. Homebrew ───────────────────────────────────────────────
if command -v brew &>/dev/null; then
    ok "Homebrew (already installed)"
else
    echo "Installing Homebrew..."
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for this script session
    if [[ "$PLATFORM" == "wsl" ]]; then
        eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
    else
        eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
    fi
    ok "Homebrew"
fi

# Ensure brew is on PATH for subsequent commands (WSL after fresh install)
if [[ "$PLATFORM" == "wsl" ]] && [[ -d /home/linuxbrew/.linuxbrew ]]; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
fi

# brew_install <pkg> [--cask]
# Idempotent: skips if formula or cask is already installed, or binary is on PATH.
brew_install() {
    local pkg="$1"
    local flag="${2:-}"
    # Check formula install, cask install, or binary presence — whichever applies
    if brew list --formula "$pkg" &>/dev/null || \
       brew list --cask "$pkg" &>/dev/null || \
       command -v "$pkg" &>/dev/null; then
        ok "$pkg (already installed)"
        return
    fi
    echo "Installing $pkg..."
    if [[ "$flag" == "--cask" ]]; then
        brew install --cask "$pkg"
    else
        brew install "$pkg"
    fi
    ok "$pkg"
}

# ── 2. Docker ─────────────────────────────────────────────────
# Step A: Ensure Docker is installed (cask check separate from daemon check)
if [[ "$PLATFORM" == "macos" ]]; then
    if ! brew list --cask docker &>/dev/null; then
        echo "Installing Docker Desktop..."
        brew install --cask docker
        ok "Docker Desktop installed"
    else
        ok "Docker Desktop (already installed)"
    fi
    # Step B: Start daemon if not running
    if ! docker info &>/dev/null 2>&1; then
        echo "Starting Docker Desktop..."
        open -a Docker
        echo "Waiting for Docker daemon (this may take ~30 seconds)..."
        timeout=120
        elapsed=0
        until docker info &>/dev/null 2>&1; do
            sleep 2
            elapsed=$((elapsed + 2))
            if [[ $elapsed -ge $timeout ]]; then
                fail "Docker daemon did not start within ${timeout}s. Open Docker Desktop manually and re-run."
            fi
        done
    fi
    ok "Docker"
else
    # WSL: install docker CLI via brew, daemon comes from Docker Desktop for Windows
    brew_install docker
    if ! docker info &>/dev/null 2>&1; then
        echo ""
        echo "⚠️  Docker daemon not running."
        echo "   On WSL: open Docker Desktop (Windows) → Settings → Resources → WSL Integration"
        echo "   → enable your distro → Apply & Restart."
        echo "   Then re-run build_barn.sh."
        fail "Docker daemon not available"
    fi
    ok "Docker"
fi

# ── 3. Node.js ────────────────────────────────────────────────
brew_install node

# ── 4. gum ───────────────────────────────────────────────────
brew_install gum

# ── 5. gh (GitHub CLI) ──────────────────────────────
brew_install gh

# ── 6. cloudflared) ─────────────────────────────────
brew_install cloudflared

# ── 7. Docker network (agents-net) ────────────────────────────
# docker-compose.yml declares agents-net as external: true.
# Create it if missing so docker compose up doesn't fail silently.
if ! docker network inspect agents-net &>/dev/null 2>&1; then
    echo "Creating Docker network: agents-net"
    docker network create agents-net
fi
ok "Docker network: agents-net"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "build_barn.sh complete."
echo "All dependencies ready."
SCRIPT
chmod +x build_barn.sh
```

- [ ] **Step 2: Smoke test — first run (installs)**

```bash
# Verify syntax first
bash -n build_barn.sh && echo "✓ Syntax OK"

# Run it (must have internet; Docker must be openable)
bash build_barn.sh
# Expected: each package shows "(already installed)" or installs fresh
# Expected exit code: 0
```

- [ ] **Step 3: Smoke test — idempotency (second run)**

```bash
bash build_barn.sh
# Expected: ALL lines show "✓ <pkg> (already installed)"
# Expected exit code: 0
```

- [ ] **Step 4: Verify all tools are available**

```bash
brew --version        && echo "✓ brew"
docker --version      && echo "✓ docker"
docker info           && echo "✓ docker daemon"
node --version        && echo "✓ node"
gum --version         && echo "✓ gum"
gh --version          && echo "✓ gh"
cloudflared --version && echo "✓ cloudflared"
docker network inspect agents-net && echo "✓ agents-net"
```

- [ ] **Step 5: Commit**

```bash
git add build_barn.sh
git commit -m "feat: add build_barn.sh — idempotent Homebrew-based dependency installer"
```

---

## Task 2: `raise_bull.sh`

**Files:**
- Create: `raise_bull.sh`

Context: Called by Claude after collecting non-sensitive config (bot name, port, domain, flags). Claude passes flags; gum collects secrets. `~/bots/<name>/workspace/` is seeded from `workspace.example/`. `.env` is written with chmod 600. The script then calls `~/bots/start-bot.sh <name>` and polls `/health`.

**Key implementation details:**

1. **base64 portability**: macOS `base64` does not support `-w 0` (Linux flag); Linux `base64` wraps at 76 chars by default. Safe cross-platform: `base64 -w 0 2>/dev/null || base64 -b 0 2>/dev/null || base64 | tr -d '\n'`

2. **`.env` values with special chars**: Use `printf '%s\n'` per-line for secrets instead of a heredoc — heredocs expand `$` in values, which corrupts tokens containing literal `$`. Non-secret lines (BOT_NAME, paths, etc.) use an **unquoted** heredoc (`<< ENVEOF`, NOT `<< 'ENVEOF'`) so that variable values expand correctly into the file.

3. **Workspace seed sentinel**: Check if workspace directory is empty (not for a specific file) — a user might delete `CLAUDE.md` but keep their identity files, and we must not overwrite them.

4. **MiniMax model name constant**: Define at top of script so it's easy to update.

- [ ] **Step 1: Create `raise_bull.sh`**

```bash
cat > raise_bull.sh << 'SCRIPT'
#!/usr/bin/env bash
# raise_bull.sh — Create and start a raise-a-bull bot instance
# Usage: bash raise_bull.sh <bot-name> [--port=18888] [--domain=DOMAIN] [--discord] [--minimax]
set -euo pipefail

# ── Constants ────────────────────────────────────────────────
MINIMAX_MODEL="MiniMax-M2.7"   # Update here when MiniMax changes their model name
DEFAULT_MODEL="claude-sonnet-4-6"

# ── Parse arguments ──────────────────────────────────────────
BOT_NAME="${1:-}"
if [[ -z "$BOT_NAME" ]]; then
    echo "Usage: raise_bull.sh <bot-name> [--port=PORT] [--domain=DOMAIN] [--discord] [--minimax]" >&2
    exit 1
fi
shift

PORT=18888
DOMAIN=""
ENABLE_DISCORD=false
ENABLE_MINIMAX=false

for arg in "$@"; do
    case "$arg" in
        --port=*)    PORT="${arg#--port=}" ;;
        --domain=*)  DOMAIN="${arg#--domain=}" ;;
        --discord)   ENABLE_DISCORD=true ;;
        --minimax)   ENABLE_MINIMAX=true ;;
        *) echo "Unknown flag: $arg" >&2; exit 1 ;;
    esac
done

REPO_DIR="$HOME/raise-a-bull"
BOT_DIR="$HOME/bots/$BOT_NAME"
WORKSPACE_DIR="$BOT_DIR/workspace"
ENV_FILE="$BOT_DIR/.env"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "raise_bull.sh — creating bot: $BOT_NAME"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Ensure engine repo is cloned ──────────────────────────
if [[ ! -d "$REPO_DIR" ]]; then
    echo "Cloning raise-a-bull engine..."
    git clone https://github.com/leepoweii/raise-a-bull.git "$REPO_DIR"
fi

# Ensure start-bot.sh is in place
if [[ ! -f "$HOME/bots/start-bot.sh" ]]; then
    mkdir -p "$HOME/bots"
    cp "$REPO_DIR/bots/start-bot.sh" "$HOME/bots/start-bot.sh"
    chmod +x "$HOME/bots/start-bot.sh"
fi

# ── 2. Create bot directories ─────────────────────────────────
mkdir -p "$WORKSPACE_DIR/data"

# ── 3. Seed workspace (skip if already has content) ───────────
# Check for any files in workspace/ — don't key on a specific file
# because the user may have deleted CLAUDE.md but kept their identity files.
if [[ -z "$(ls -A "$WORKSPACE_DIR" 2>/dev/null)" ]]; then
    echo "Seeding workspace from template..."
    cp -r "$REPO_DIR/workspace.example/." "$WORKSPACE_DIR/"
    echo "✓ Workspace seeded — edit $WORKSPACE_DIR/identity/ to personalize your bot"
else
    echo "✓ Workspace already has content — skipping seed"
fi

# ── 4. Read Claude credentials ────────────────────────────────
CREDS_FILE="$HOME/.claude/.credentials.json"
if [[ ! -f "$CREDS_FILE" ]]; then
    echo "ERROR: ~/.claude/.credentials.json not found." >&2
    echo "Make sure Claude Code is installed and you are logged in: claude --version" >&2
    exit 1
fi
# base64 portability: macOS uses -b 0, Linux uses -w 0, fallback strips newlines
CLAUDE_CREDENTIALS=$(base64 -w 0 "$CREDS_FILE" 2>/dev/null \
    || base64 -b 0 "$CREDS_FILE" 2>/dev/null \
    || base64 "$CREDS_FILE" | tr -d '\n')
echo "✓ Claude credentials read"

# ── 5. Collect secrets via gum ───────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Secrets Setup"
echo "Your keys stay local — never sent to Claude."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

LINE_SECRET=$(gum input --password --placeholder "LINE Channel Secret" --prompt "? LINE Channel Secret  ")
LINE_TOKEN=$(gum input --password --placeholder "LINE Channel Access Token" --prompt "? LINE Access Token    ")
LINE_USER_ID=$(gum input --placeholder "LINE User ID (Uxxxxx...)" --prompt "? LINE User ID         ")

DISCORD_TOKEN=""
DISCORD_GUILD=""
if [[ "$ENABLE_DISCORD" == "true" ]]; then
    DISCORD_TOKEN=$(gum input --password --placeholder "Discord Bot Token" --prompt "? Discord Bot Token    ")
    DISCORD_GUILD=$(gum input --placeholder "Discord Guild/Server ID" --prompt "? Discord Guild ID     ")
fi

MINIMAX_KEY=""
if [[ "$ENABLE_MINIMAX" == "true" ]]; then
    MINIMAX_KEY=$(gum input --password --placeholder "sk-api-..." --prompt "? MiniMax API Key      ")
fi

# ── 6. Write .env (chmod 600) ─────────────────────────────────
# Non-secret config written via UNQUOTED heredoc (<< ENVEOF, not << 'ENVEOF').
# Variables like $BOT_NAME and $PORT intentionally expand here — that's the point.
# Secrets are written via printf to protect against $ in token values (e.g. LINE secrets).
CLAUDE_MODEL_VALUE="$DEFAULT_MODEL"
if [[ "$ENABLE_MINIMAX" == "true" ]]; then
    CLAUDE_MODEL_VALUE="$MINIMAX_MODEL"
fi

# Start with non-secret config (unquoted heredoc — variables expand intentionally)
cat > "$ENV_FILE" << ENVEOF
# --- Compose-level vars ---
BOT_NAME=$BOT_NAME
BOT_PORT=$PORT
WORKSPACE_PATH=$WORKSPACE_DIR

# --- Container env vars ---
CLAUDE_BIN=claude
CLAUDE_MODEL=$CLAUDE_MODEL_VALUE
WORKSPACE=/app/workspace
DB_PATH=/app/workspace/data/sessions.db
MAX_DAILY_HEARTBEAT_TRIGGERS=20

# --- LINE ---
ENVEOF

# Append secrets via printf (protects against $ in token values)
printf 'LINE_CHANNEL_SECRET=%s\n' "$LINE_SECRET" >> "$ENV_FILE"
printf 'LINE_CHANNEL_ACCESS_TOKEN=%s\n' "$LINE_TOKEN" >> "$ENV_FILE"
printf 'LINE_USER_ID=%s\n' "$LINE_USER_ID" >> "$ENV_FILE"

printf '\n# --- Discord ---\n' >> "$ENV_FILE"
printf 'DISCORD_BOT_TOKEN=%s\n' "$DISCORD_TOKEN" >> "$ENV_FILE"
printf 'DISCORD_GUILD_ID=%s\n' "$DISCORD_GUILD" >> "$ENV_FILE"

printf '\n# --- Claude Credentials ---\n' >> "$ENV_FILE"
printf 'CLAUDE_CREDENTIALS=%s\n' "$CLAUDE_CREDENTIALS" >> "$ENV_FILE"

if [[ "$ENABLE_MINIMAX" == "true" ]]; then
    printf '\n# --- MiniMax ---\n' >> "$ENV_FILE"
    printf 'MINIMAX_API_KEY=%s\n' "$MINIMAX_KEY" >> "$ENV_FILE"
fi

chmod 600 "$ENV_FILE"
echo ""
echo "✓ .env written (chmod 600)"

# ── 7. Start the bot ──────────────────────────────────────────
echo "Starting $BOT_NAME..."
bash "$HOME/bots/start-bot.sh" "$BOT_NAME"

# ── 8. Wait for /health ───────────────────────────────────────
echo "Waiting for bot to be healthy..."
timeout=90
elapsed=0
until curl -sf "http://localhost:$PORT/health" &>/dev/null; do
    sleep 3
    elapsed=$((elapsed + 3))
    if [[ $elapsed -ge $timeout ]]; then
        echo "Bot did not respond within ${timeout}s. Check logs:" >&2
        echo "  docker logs bull-$BOT_NAME --tail 30" >&2
        exit 1
    fi
done

# ── 9. Print webhook URL ──────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✓ Bot is running!"
echo ""
if [[ -n "$DOMAIN" ]]; then
    echo "Webhook URL: https://$DOMAIN/webhook/line"
else
    echo "Next step: start a Cloudflare tunnel to get your webhook URL:"
    echo "  cloudflared tunnel --url http://localhost:$PORT"
    echo ""
    echo "Then set webhook URL in LINE Developers Console:"
    echo "  https://<your-tunnel>.trycloudflare.com/webhook/line"
fi
echo ""
echo "Logs: docker logs bull-$BOT_NAME --tail 30"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SCRIPT
chmod +x raise_bull.sh
```

- [ ] **Step 2: Smoke test — syntax and arg parsing**

```bash
# Verify syntax
bash -n raise_bull.sh && echo "✓ Syntax OK"

# Test missing name (does not run any git/docker side effects — exits immediately)
bash raise_bull.sh 2>&1 | grep -q "Usage:" && echo "✓ Usage shown when no name"

# Note: testing --bad-flag requires the repo to be cloned (the script clones it first).
# If ~/raise-a-bull already exists: bash raise_bull.sh testbot --bad-flag 2>&1 | grep -q "Unknown flag"
# Otherwise skip this test on first run — flag parsing is covered by the case statement above.
```

- [ ] **Step 3: Smoke test — .env format and base64 (isolated test)**

```bash
cat > /tmp/test_env_write.sh << 'EOF'
#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=/tmp/test_raise_bull.env
CREDS_FILE=/tmp/fake_credentials.json
echo '{"token":"test123"}' > "$CREDS_FILE"

# Test cross-platform base64 (same logic as raise_bull.sh)
CLAUDE_CREDENTIALS=$(base64 -w 0 "$CREDS_FILE" 2>/dev/null \
    || base64 -b 0 "$CREDS_FILE" 2>/dev/null \
    || base64 "$CREDS_FILE" | tr -d '\n')

# Verify single-line output (no embedded newlines)
LINE_COUNT=$(echo "$CLAUDE_CREDENTIALS" | wc -l | tr -d ' ')
[[ "$LINE_COUNT" == "1" ]] && echo "✓ base64 is single line" || echo "✗ base64 has $LINE_COUNT lines"

# Simulate .env write with a secret that contains $ (the problem case)
LINE_SECRET='test$secret'
LINE_TOKEN='token$with$dollars'
LINE_USER_ID='U1234567890'
DISCORD_TOKEN=""
DISCORD_GUILD=""
BOT_NAME=testbot; PORT=19999
WORKSPACE_DIR=/tmp/test_workspace

cat > "$ENV_FILE" << ENVEOF
BOT_NAME=$BOT_NAME
BOT_PORT=$PORT
WORKSPACE_PATH=$WORKSPACE_DIR
ENVEOF

printf 'LINE_CHANNEL_SECRET=%s\n' "$LINE_SECRET" >> "$ENV_FILE"
printf 'LINE_CHANNEL_ACCESS_TOKEN=%s\n' "$LINE_TOKEN" >> "$ENV_FILE"
printf 'LINE_USER_ID=%s\n' "$LINE_USER_ID" >> "$ENV_FILE"
printf 'CLAUDE_CREDENTIALS=%s\n' "$CLAUDE_CREDENTIALS" >> "$ENV_FILE"

chmod 600 "$ENV_FILE"

# Verify: the literal $ is preserved in the value
grep -q 'LINE_CHANNEL_SECRET=test\$secret' "$ENV_FILE" && echo "✓ $ preserved in secret value" || echo "✗ $ was expanded"
grep -q "BOT_NAME=testbot" "$ENV_FILE" && echo "✓ BOT_NAME"
grep -q "CLAUDE_CREDENTIALS=" "$ENV_FILE" && echo "✓ CLAUDE_CREDENTIALS present"
PERMS=$(stat -c %a "$ENV_FILE" 2>/dev/null || stat -f %OLp "$ENV_FILE")
[[ "$PERMS" == "600" ]] && echo "✓ chmod 600" || echo "✗ Wrong permissions: $PERMS"

rm "$ENV_FILE" "$CREDS_FILE"
EOF
bash /tmp/test_env_write.sh
```

- [ ] **Step 4: Commit**

```bash
git add raise_bull.sh
git commit -m "feat: add raise_bull.sh — bot instance creator with gum-secured secret input"
```

---

## Task 3: Add `bots/start-bot.sh` and `bots/upgrade_bull.sh` to repo

**Files:**
- Create: `bots/start-bot.sh`
- Create: `bots/upgrade_bull.sh`

Context: These files exist on samantha-wsl at `~/bots/` but were never committed to the repo. They live at `bots/` in the repo so `raise_bull.sh` can copy them during setup. **Do not confuse paths**: `bots/start-bot.sh` is in the repo; `~/bots/start-bot.sh` is where it lives on the user's machine.

Fix from review: replace `export $(grep ... | xargs)` with `set -a; source` to handle paths with spaces correctly.

**Upgrade story:** Because the engine (`~/raise-a-bull/`) and context (`~/bots/<name>/workspace/`) are fully separated, upgrades are clean — `git pull` updates the engine code, restart rebuilds the Docker image, context is never touched. `upgrade_bull.sh` packages this into one command for non-technical users.

- [ ] **Step 1: Create `bots/start-bot.sh` in the repo**

```bash
mkdir -p bots
cat > bots/start-bot.sh << 'SCRIPT'
#!/usr/bin/env bash
# start-bot.sh — Launch a raise-a-bull bot instance
# Usage: bash start-bot.sh <bot-name>
# Copy this to ~/bots/start-bot.sh on the host machine (raise_bull.sh does this automatically).
set -e

BOT="$1"
if [[ -z "$BOT" ]]; then
    echo "Usage: $0 <bot-name>"
    exit 1
fi

BOT_DIR="$HOME/bots/$BOT"
ENV_FILE="$BOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Run raise_bull.sh first." >&2
    exit 1
fi

# Load compose-level vars from .env.
# Using set -a / source instead of export $(xargs) to handle paths with spaces.
set -a
# shellcheck source=/dev/null
source <(grep -E '^(BOT_NAME|BOT_PORT|WORKSPACE_PATH)=' "$ENV_FILE")
set +a

export BOT_ENV_FILE="$ENV_FILE"

cd "$HOME/raise-a-bull"
docker compose -p "bull-$BOT" up -d --build

echo "Started bull-$BOT on port $BOT_PORT"
SCRIPT
chmod +x bots/start-bot.sh
```

- [ ] **Step 2: Create `bots/upgrade_bull.sh` in the repo**

```bash
cat > bots/upgrade_bull.sh << 'SCRIPT'
#!/usr/bin/env bash
# upgrade_bull.sh — Upgrade raise-a-bull engine and restart a bot instance
# Usage: bash upgrade_bull.sh <bot-name>
# Copy this to ~/bots/upgrade_bull.sh on the host machine.
#
# What it does:
#   1. git pull in ~/raise-a-bull/ (engine only — your workspace/identity/memory are untouched)
#   2. Restart the bot container (rebuilds Docker image from updated code)
set -euo pipefail

BOT="${1:-}"
if [[ -z "$BOT" ]]; then
    echo "Usage: $0 <bot-name>"
    exit 1
fi

REPO_DIR="$HOME/raise-a-bull"

if [[ ! -d "$REPO_DIR" ]]; then
    echo "ERROR: $REPO_DIR not found. Run raise_bull.sh first." >&2
    exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Upgrading raise-a-bull engine..."
echo "(Your workspace, identity, memory, and sessions are untouched)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$REPO_DIR"
git pull origin main

echo ""
echo "Restarting bull-$BOT..."
bash "$HOME/bots/start-bot.sh" "$BOT"

echo ""
echo "✓ bull-$BOT upgraded and restarted"
SCRIPT
chmod +x bots/upgrade_bull.sh
```

- [ ] **Step 3: Verify syntax**

```bash
bash -n bots/start-bot.sh    && echo "✓ start-bot.sh syntax OK"
bash -n bots/upgrade_bull.sh && echo "✓ upgrade_bull.sh syntax OK"
```

- [ ] **Step 4: Update `raise_bull.sh` to also copy `upgrade_bull.sh`**

In `raise_bull.sh`, find the block that copies `start-bot.sh` and add the upgrade script alongside it:

```bash
# In raise_bull.sh — replace the start-bot.sh copy block with:
if [[ ! -f "$HOME/bots/start-bot.sh" ]]; then
    mkdir -p "$HOME/bots"
    cp "$REPO_DIR/bots/start-bot.sh" "$HOME/bots/start-bot.sh"
    chmod +x "$HOME/bots/start-bot.sh"
fi
if [[ ! -f "$HOME/bots/upgrade_bull.sh" ]]; then
    cp "$REPO_DIR/bots/upgrade_bull.sh" "$HOME/bots/upgrade_bull.sh"
    chmod +x "$HOME/bots/upgrade_bull.sh"
fi
```

- [ ] **Step 5: Commit**

```bash
git add bots/start-bot.sh bots/upgrade_bull.sh
git commit -m "feat: add bots/start-bot.sh and upgrade_bull.sh to repo

upgrade_bull.sh: git pull engine + restart bot in one command.
Context (workspace, identity, memory, sessions.db) is never touched."
```

---

## Task 4: Create `docs/screenshots/` placeholder

**Files:**
- Create: `docs/screenshots/.gitkeep`
- Create: `docs/screenshots/README.md`

- [ ] **Step 1: Create placeholder**

```bash
mkdir -p docs/screenshots
touch docs/screenshots/.gitkeep
cat > docs/screenshots/README.md << 'EOF'
# Screenshot Guides

Visual step-by-step guides for external service console navigation.
Referenced by `docs/install-guide-for-claude.md` during onboarding.

## Planned guides

- `line/` — LINE Developers Console: create channel, get credentials, set webhook
- `cloudflare/` — Cloudflare Zero Trust: create named tunnel, DNS setup
- `discord/` — Discord Developer Portal: create bot, get token, invite to server
- `minimax/` — MiniMax Platform: get API key
EOF
```

- [ ] **Step 2: Commit**

```bash
git add docs/screenshots/
git commit -m "chore: add docs/screenshots/ placeholder for visual onboarding guides"
```

---

## Task 5: Rewrite `docs/install-guide-for-claude.md`

**Files:**
- Modify: `docs/install-guide-for-claude.md`

Context: The current guide (314 lines) pre-dates the new design. Replace it entirely. The new guide is a **Claude-facing instruction document** — not a user manual. Claude reads it and orchestrates the user through the process.

Key differences from old guide:
- Opens with security warning (secrets never in chat)
- Claude dispatches a subagent to run `build_barn.sh` in background
- Claude guides account setup interactively while build_barn runs
- Claude calls `raise_bull.sh` with flags (described in prose, not bracket notation) — no manual `.env` editing
- Security warning shown again before raise_bull.sh
- Common Errors table includes `agents-net` failure

- [ ] **Step 1: Rewrite `docs/install-guide-for-claude.md`**

Replace the entire file with:

````markdown
---
name: raise-a-bull-install
description: Use when helping a user install and set up raise-a-bull — a Claude Code bot framework for LINE and Discord. Orchestrates full installation from prerequisites to first bot response.
---

# raise-a-bull Installation Guide (Claude Orchestration)

## Your role

You are orchestrating the complete raise-a-bull onboarding. Work interactively — confirm each step before proceeding. You run the technical steps; the user handles web consoles.

> ⚠️ **SECURITY — Show this immediately, before anything else:**
>
> "Do NOT paste any tokens, secrets, or API keys into this chat.
> Store everything in a local notepad as you collect it.
> You will enter secrets securely in the terminal at the very end."

---

## Phase 1 — Verify Prerequisites

Claude Code is already running (that's how the user opened this guide). Check git:

```bash
git --version && echo "✓ git"
```

If git is missing, ask the user to install it before continuing.

---

## Phase 2 — Install Dependencies (background subagent)

Clone the engine repo and dispatch a subagent to run `build_barn.sh` while you guide account setup in parallel.

```bash
# Clone engine repo if not already present
if [ ! -d ~/raise-a-bull ]; then
  git clone https://github.com/leepoweii/raise-a-bull.git ~/raise-a-bull
fi
```

Dispatch a **background subagent** to run:
```bash
bash ~/raise-a-bull/build_barn.sh
```

Tell the user: "I'm installing dependencies in the background — this takes a few minutes. While that runs, let's set up your accounts."

---

## Phase 3 — LINE Bot Setup

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

Leave this browser tab open — you'll paste the webhook URL here in Phase 10.

*Reference: docs/screenshots/line/ (guides coming soon)*

---

## Phase 4 — Cloudflare Tunnel (choose one)

Ask the user:

> "Do you want a permanent webhook URL (named tunnel) or a temporary one (quick tunnel — changes on restart)?"

**Option A — Quick tunnel (easier, good for testing):**
No setup needed now. You'll start it in Phase 10 with one command.

**Option B — Named tunnel (production):**
Ask the user for their tunnel domain (e.g. `bot.example.com`). They need a Cloudflare account with a domain and the tunnel configured. Record the domain for Phase 8.

*Reference: docs/screenshots/cloudflare/ (guides coming soon)*

---

## Phase 5 — Discord (optional)

Ask: "Do you want Discord support in addition to LINE?"

If yes, guide them through https://discord.com/developers/applications:

1. New Application → name it
2. Bot tab → Add Bot → Reset Token → copy → save to notepad as Discord Token
3. Enable **Message Content Intent** (Bot tab)
4. OAuth2 → URL Generator → scopes: `bot`, `applications.commands` → permissions: `Send Messages`, `Read Message History` → copy generated URL → open in browser → authorize to their server
5. Right-click server name in Discord → Copy Server ID → save to notepad as Discord Guild ID

*Reference: docs/screenshots/discord/ (guides coming soon)*

---

## Phase 6 — MiniMax (optional — shared/team use only)

Ask: "Will this bot be shared among multiple users (e.g. a group LINE chat with different people)?"

If yes, MiniMax is required (avoids violating Claude single-account policy):
Guide them to https://platform.minimax.io → get API key → save to notepad.

If no (personal single-user bot): skip this phase.

*Reference: docs/screenshots/minimax/ (guides coming soon)*

---

## Phase 7 — Confirm build_barn.sh Complete

Check that the background subagent from Phase 2 has finished. Verify:

```bash
docker --version      && echo "✓ Docker"
docker info           && echo "✓ Docker daemon"
node --version        && echo "✓ Node"
gum --version         && echo "✓ gum"
cloudflared --version && echo "✓ cloudflared"
```

All must show ✓. If any fail, run `bash ~/raise-a-bull/build_barn.sh` directly and wait.

---

## Phase 8 — Create Bot Instance

Collect from the user (non-sensitive — ask in chat):
- Bot name (e.g. `mybot`)
- Port (default: `18888`)
- Tunnel domain from Phase 4, or none (quick tunnel)
- Whether to enable Discord (from Phase 5)
- Whether to enable MiniMax (from Phase 6)

> ⚠️ **SECURITY REMINDER — Show this again before running raise_bull.sh:**
>
> "About to enter secrets. Your terminal will prompt you for each key.
> Type or paste ONLY into the terminal prompts — not here in chat."

Build the command based on what you collected and run it. For example:

```bash
# Always include --port. Add --domain only if they have a named tunnel.
# Add --discord only if Phase 5 was completed. Add --minimax only if Phase 6 was completed.
bash ~/raise-a-bull/raise_bull.sh mybot --port=18888

# With named tunnel: bash ~/raise-a-bull/raise_bull.sh mybot --port=18888 --domain=bot.example.com
# With Discord:      add --discord
# With MiniMax:      add --minimax
```

The script will:
- Seed `~/bots/mybot/workspace/` from the template
- Prompt for all secrets in the terminal (not in chat)
- Write `~/bots/mybot/.env` (chmod 600)
- Start the Docker container
- Wait for /health and print the webhook URL

---

## Phase 9 — Personalize Bot Identity

After raise_bull.sh completes, open the identity files:

```bash
$EDITOR ~/bots/mybot/workspace/identity/profile.md   # bot name, personality, tone
$EDITOR ~/bots/mybot/workspace/identity/context.md   # about the owner
```

`expertise.md` is optional — fill in if the bot has a specialized focus.

---

## Phase 10 — Set Webhook URL

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

## Phase 11 — Verify

1. Open LINE → find the bot by Basic ID (Basic Settings → Bot basic ID, starts with `@`) → Add as friend
2. Send "hi"
3. Bot should respond within 10–30 seconds

Check logs while waiting:
```bash
docker logs bull-mybot --tail 30 -f
```

---

## Common Errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `LINE_CHANNEL_SECRET must be set` | Empty env var | Re-run raise_bull.sh |
| Webhook Verify fails 404 | Wrong URL path | URL must end with `/webhook/line` |
| Container exits immediately | Bad `CLAUDE_CREDENTIALS` | Check `~/.claude/.credentials.json` exists and re-run raise_bull.sh |
| Bot says "(no response)" | Claude invocation error | Check `docker logs bull-mybot` |
| Discord bot offline | Missing Message Content Intent | Enable on Discord Developer Portal |
| `network agents-net not found` | Docker network missing | Run `docker network create agents-net` then retry |

### Finding LINE_USER_ID from logs

If you skipped LINE User ID in Phase 3:
1. Make sure bot is running and webhook is set
2. Add bot on LINE and send any message
3. Run: `docker logs bull-mybot | grep "line:U"`
4. Copy the `Uxxxxxxxxxxxxxxxx` value → edit `~/bots/mybot/.env` → restart: `bash ~/bots/start-bot.sh mybot`

---

## Adding a Second Bot

Run raise_bull.sh again with a different name and port:

```bash
bash ~/raise-a-bull/raise_bull.sh workbot --port=18889
# Add --discord / --minimax as needed
```

Each instance runs independently on its own port with its own workspace and identity.
````

- [ ] **Step 2: Verify the file was written**

```bash
wc -l docs/install-guide-for-claude.md
head -5 docs/install-guide-for-claude.md
# Should start with: ---
grep -c "SECURITY" docs/install-guide-for-claude.md
# Should be 2 (one at start, one before Phase 8)
```

- [ ] **Step 3: Commit**

```bash
git add docs/install-guide-for-claude.md
git commit -m "docs: rewrite install-guide-for-claude.md for new Claude Code orchestration model

- Claude Code is the entry point (minimum competency gate)
- Security warnings shown at start and again before raise_bull.sh
- Subagent dispatches build_barn.sh in background during account setup
- No manual .env editing: raise_bull.sh handles all secrets via gum
- Aligned with onboarding design spec 2026-03-19"
```

---

## Task 6: Update `README.md` Quick Start

**Files:**
- Modify: `README.md`

Context: Update the Quick Start section to point to Claude Code as the entry point. The correct way to reference a file in Claude Code is `@path/to/file.md` (not `/path`). Leave the rest of the README intact.

- [ ] **Step 1: Find the Quick Start section**

```bash
grep -n "Quick Start\|quick-start\|## Getting" README.md | head -10
```

Note the line range.

- [ ] **Step 2: Replace the Quick Start section**

Find and replace the Quick Start content with:

```markdown
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
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update Quick Start — Claude Code as entry point, correct @ file reference syntax"
```

---

## Task 7: Final verification

- [ ] **Step 1: Check all files exist and are syntactically valid**

```bash
ls -la build_barn.sh raise_bull.sh bots/start-bot.sh bots/upgrade_bull.sh
bash -n build_barn.sh         && echo "✓ build_barn.sh syntax"
bash -n raise_bull.sh         && echo "✓ raise_bull.sh syntax"
bash -n bots/start-bot.sh     && echo "✓ start-bot.sh syntax"
bash -n bots/upgrade_bull.sh  && echo "✓ upgrade_bull.sh syntax"
ls docs/screenshots/       && echo "✓ screenshots dir"
wc -l docs/install-guide-for-claude.md
```

- [ ] **Step 2: Verify git log**

```bash
git log --oneline -7
# Should show one commit per task above
```

- [ ] **Step 3: Push to main**

```bash
git push origin main
```

- [ ] **Step 4: Sync to samantha-wsl**

```bash
ssh samantha-wsl "cd ~/raise-a-bull && git pull origin main"
ssh samantha-wsl "ls build_barn.sh raise_bull.sh bots/start-bot.sh"
```

Expected: all three scripts present on the server.
