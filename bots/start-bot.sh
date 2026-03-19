#!/usr/bin/env bash
# start-bot.sh — Launch a raise-a-bull bot instance
# Usage: bash start-bot.sh <bot-name>
# Copy this to ~/bots/start-bot.sh on the host machine (raise_bull.sh does this automatically).
set -euo pipefail

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
