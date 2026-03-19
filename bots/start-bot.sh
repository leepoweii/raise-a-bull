#!/usr/bin/env bash
# start-bot.sh — Launch a raise-a-bull bot instance
# Usage: bash start-bot.sh <bot-name> --root=<project-root>
# Lives in engine/bots/ — no need to copy anywhere.
set -euo pipefail

BOT="${1:-}"
if [[ -z "$BOT" ]]; then
    echo "Usage: $0 <bot-name> --root=<project-root>" >&2
    exit 1
fi
shift

# Parse --root
PROJECT_ROOT=""
for arg in "$@"; do
    case "$arg" in
        --root=*) PROJECT_ROOT="${arg#--root=}" ;;
    esac
done

# Fallback: discover root from script location (engine/bots/start-bot.sh → engine → root)
if [[ -z "$PROJECT_ROOT" ]]; then
    PROJECT_ROOT="${RAISE_A_BULL_ROOT:-}"
fi
if [[ -z "$PROJECT_ROOT" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
fi

ENGINE_DIR="$PROJECT_ROOT/engine"
BOT_DIR="$PROJECT_ROOT/$BOT"
ENV_FILE="$BOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Run raise_bull.sh first." >&2
    exit 1
fi

# Load compose-level vars from .env and export them for docker compose.
set -a
eval "$(grep -E '^(BOT_NAME|BOT_PORT|WORKSPACE_PATH)=' "$ENV_FILE")"
set +a

export BOT_ENV_FILE="$ENV_FILE"

cd "$ENGINE_DIR"

# Support both docker compose v2 (subcommand) and v1 (docker-compose)
if docker compose version &>/dev/null; then
    docker compose -p "bull-$BOT" up -d --build
elif command -v docker-compose &>/dev/null; then
    docker-compose -p "bull-$BOT" up -d --build
else
    echo "ERROR: Neither 'docker compose' nor 'docker-compose' found." >&2
    exit 1
fi

echo "Started bull-$BOT on port $BOT_PORT"
