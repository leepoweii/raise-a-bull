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

exec "$@"
