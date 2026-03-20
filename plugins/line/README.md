# claude-channel-line

LINE Messaging API channel plugin for Claude Code.

Connects your Claude Code session to LINE, allowing you to receive and send LINE messages through a persistent Claude Code session.

## Prerequisites

- [Bun](https://bun.sh) runtime
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) (for auto-tunnel, install: `brew install cloudflared`)
- A LINE Messaging API channel ([LINE Developer Console](https://developers.line.biz/console/))

## Quick Start

```bash
claude --channels plugin:line
```

On first run, you'll be prompted to configure your LINE credentials:

```
/line:configure token
```

The plugin will:
1. Start a local HTTP server for LINE webhooks
2. Create a cloudflared tunnel automatically
3. Set the webhook URL on LINE
4. Begin receiving messages

## Tunnel Options

| User | Command |
|------|---------|
| Default (zero config) | `claude --channels plugin:line` |
| Own domain | `claude --channels plugin:line -- --tunnel-url https://bot.example.com` |
| Port already exposed | `claude --channels plugin:line -- --no-tunnel --port 8000` |

## Access Control

By default, the plugin uses **pairing mode**:
1. Unknown user messages your bot
2. Bot replies with a pairing code and their user ID
3. You run `/line:access pair <CODE>` in Claude Code to approve

See `ACCESS.md` for full details.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `LINE_CHANNEL_SECRET` | Channel secret from LINE Developer Console |
| `LINE_CHANNEL_ACCESS_TOKEN` | Long-lived channel access token |
| `LINE_PORT` | HTTP server port (default: 3000) |
| `LINE_BOT_USER_ID` | Bot's own user ID (auto-detected, fallback for mention detection) |

Environment variables override the `.env` file at `~/.claude/channels/line/.env`.

## Tools

| Tool | Description |
|------|-------------|
| `reply` | Reply to a message (free via reply token, falls back to push) |
| `push_message` | Send proactive message (costs quota) |
| `get_profile` | Get user's display name and picture |
