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
        --port=*)    PORT="${arg#--port=}"
                     [[ "$PORT" =~ ^[0-9]+$ ]] || { echo "ERROR: --port must be a number, got: $PORT" >&2; exit 1; }
                     ;;
        --domain=*)  DOMAIN="${arg#--domain=}" ;;
        --discord)   ENABLE_DISCORD=true ;;
        --minimax)   ENABLE_MINIMAX=true ;;
        *) echo "Unknown flag: $arg" >&2; exit 1 ;;
    esac
done

if ! command -v gum &>/dev/null; then
    echo "ERROR: 'gum' is required but not found. Run build_barn.sh first." >&2
    exit 1
fi

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

# Ensure start-bot.sh is in place (upgrade_bull.sh added in next step)
mkdir -p "$HOME/bots"
if [[ ! -f "$HOME/bots/start-bot.sh" ]]; then
    cp "$REPO_DIR/bots/start-bot.sh" "$HOME/bots/start-bot.sh"
    chmod +x "$HOME/bots/start-bot.sh"
fi
if [[ ! -f "$HOME/bots/upgrade_bull.sh" ]]; then
    cp "$REPO_DIR/bots/upgrade_bull.sh" "$HOME/bots/upgrade_bull.sh"
    chmod +x "$HOME/bots/upgrade_bull.sh"
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
CREDS_RAW=""

if [[ -f "$CREDS_FILE" ]]; then
    CREDS_RAW=$(cat "$CREDS_FILE")
    echo "✓ Claude credentials read from file"
elif command -v security &>/dev/null; then
    # macOS Keychain: newer Claude Code stores credentials here
    CREDS_RAW=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null || true)
    if [[ -n "$CREDS_RAW" ]]; then
        echo "✓ Claude credentials read from macOS Keychain"
    fi
fi

if [[ -z "$CREDS_RAW" ]]; then
    echo "ERROR: Claude credentials not found." >&2
    echo "Checked: ~/.claude/.credentials.json and macOS Keychain (Claude Code-credentials)" >&2
    echo "Make sure Claude Code is installed and you are logged in: claude --version" >&2
    exit 1
fi

# base64 portability: macOS uses -b 0, Linux uses -w 0, fallback strips newlines
CLAUDE_CREDENTIALS=$(
    printf '%s' "$CREDS_RAW" | base64 -w 0 2>/dev/null \
    || printf '%s' "$CREDS_RAW" | base64 -b 0 2>/dev/null \
    || printf '%s' "$CREDS_RAW" | base64
)
CLAUDE_CREDENTIALS="${CLAUDE_CREDENTIALS//$'\n'/}"

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

# Create .env with correct permissions atomically before writing any secrets
install -m 600 /dev/null "$ENV_FILE"

# Start with non-secret config (unquoted heredoc — variables expand intentionally)
cat > "$ENV_FILE" << ENVEOF
# --- Compose-level vars ---
BOT_NAME="$BOT_NAME"
BOT_PORT=$PORT
WORKSPACE_PATH="$WORKSPACE_DIR"

# --- Container env vars ---
CLAUDE_BIN=claude
CLAUDE_MODEL="$CLAUDE_MODEL_VALUE"
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
    echo "  ...waiting (${elapsed}s / ${timeout}s)"
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
