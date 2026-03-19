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

if [[ ! -f "$HOME/bots/start-bot.sh" ]]; then
    echo "ERROR: ~/bots/start-bot.sh not found. Run raise_bull.sh first." >&2
    exit 1
fi

if [[ ! -f "$HOME/bots/$BOT/.env" ]]; then
    echo "ERROR: ~/bots/$BOT/.env not found. Run: bash raise_bull.sh $BOT" >&2
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
