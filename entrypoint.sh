#!/bin/sh
set -e

# Bootstrap Claude credentials from env var on first run
if [ -n "$CLAUDE_CREDENTIALS" ] && [ ! -f "/home/bull/.claude/.credentials.json" ]; then
    echo "Bootstrapping Claude credentials..."
    mkdir -p /home/bull/.claude
    if ! printf '%s' "$CLAUDE_CREDENTIALS" | base64 -d > /home/bull/.claude/.credentials.json 2>/dev/null; then
        echo "ERROR: CLAUDE_CREDENTIALS is not valid base64. Check the env var." >&2
        rm -f /home/bull/.claude/.credentials.json
        exit 1
    fi
    chmod 600 /home/bull/.claude/.credentials.json
    echo "Claude credentials written."
fi

# Write MiniMax settings.json if MINIMAX_API_KEY is set (idempotent — overwrites each start)
if [ -n "$MINIMAX_API_KEY" ]; then
    mkdir -p /home/bull/.claude
    cat > /home/bull/.claude/settings.json <<SETTINGS
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
    "ANTHROPIC_AUTH_TOKEN": "$MINIMAX_API_KEY",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": 1,
    "ANTHROPIC_MODEL": "$CLAUDE_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL": "$CLAUDE_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "$CLAUDE_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "$CLAUDE_MODEL"
  }
}
SETTINGS
    echo "MiniMax settings.json written."
fi

# Enforce correct permissions on credentials file (every startup)
if [ -f /home/bull/.claude/.credentials.json ]; then
    chmod 600 /home/bull/.claude/.credentials.json 2>/dev/null || true
fi

# Seed workspace from example if empty (first deploy on Zeabur)
if [ -d "/app/workspace.example" ] && [ -z "$(ls -A /app/workspace 2>/dev/null)" ]; then
    echo "Seeding workspace from workspace.example..."
    mkdir -p /app/workspace
    cp -r /app/workspace.example/. /app/workspace/
    find /app/workspace -name .gitkeep -delete
    echo "Workspace seeded."
fi

exec "$@"
