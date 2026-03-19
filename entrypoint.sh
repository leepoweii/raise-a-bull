#!/bin/sh
set -e

# Bootstrap Claude credentials from env var on first run
if [ -n "$CLAUDE_CREDENTIALS" ] && [ ! -f "/root/.claude/.credentials.json" ]; then
    echo "Bootstrapping Claude credentials..."
    mkdir -p /root/.claude
    if ! printf '%s' "$CLAUDE_CREDENTIALS" | base64 -d > /root/.claude/.credentials.json 2>/dev/null; then
        echo "ERROR: CLAUDE_CREDENTIALS is not valid base64. Check the env var." >&2
        rm -f /root/.claude/.credentials.json
        exit 1
    fi
    chmod 600 /root/.claude/.credentials.json
    echo "Claude credentials written."
fi

# Enforce correct permissions on credentials file (every startup)
if [ -f /root/.claude/.credentials.json ]; then
    chmod 600 /root/.claude/.credentials.json 2>/dev/null || true
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
