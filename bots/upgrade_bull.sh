#!/usr/bin/env bash
# upgrade_bull.sh — Upgrade raise-a-bull engine and restart a bot instance
# Usage: bash upgrade_bull.sh <bot-name> --root=<project-root>
#
# What it does:
#   1. git pull in engine/ (engine only — your workspace/identity/memory are untouched)
#   2. Restart the bot container (rebuilds Docker image from updated code)
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

# Expand ~ to $HOME (tilde doesn't expand inside variables)
PROJECT_ROOT="${PROJECT_ROOT/#\~/$HOME}"

# Fallback: discover root from script location (engine/bots/upgrade_bull.sh → engine → root)
if [[ -z "$PROJECT_ROOT" ]]; then
    PROJECT_ROOT="${RAISE_A_BULL_ROOT:-}"
fi
if [[ -z "$PROJECT_ROOT" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
fi

ENGINE_DIR="$PROJECT_ROOT/engine"
BOT_DIR="$PROJECT_ROOT/$BOT"

if [[ ! -d "$ENGINE_DIR" ]]; then
    echo "ERROR: $ENGINE_DIR not found. Run raise_bull.sh first." >&2
    exit 1
fi

if [[ ! -f "$BOT_DIR/.env" ]]; then
    echo "ERROR: $BOT_DIR/.env not found. Run: bash raise_bull.sh $BOT --root=$PROJECT_ROOT" >&2
    exit 1
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Upgrading raise-a-bull engine..."
echo "(Your workspace, identity, memory, and sessions are untouched)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$ENGINE_DIR"
git pull origin main

echo ""
echo "Restarting bull-$BOT..."
bash "$ENGINE_DIR/bots/start-bot.sh" "$BOT" --root="$PROJECT_ROOT"

echo ""
echo "✓ bull-$BOT upgraded and restarted"
