# LINE Channel Plugin for Claude Code

**Date:** 2026-03-20
**Status:** Approved
**Scope:** Standalone LINE Messaging API channel plugin for Claude Code, following Anthropic's Discord/Telegram plugin patterns

---

## Problem

Claude Code has official channel plugins for Discord and Telegram, but not LINE. LINE Messaging API requires an HTTP webhook endpoint — unlike Discord (WebSocket gateway) and Telegram (polling) — making it architecturally unique among channel plugins. Building a LINE plugin enables Claude Code to become a persistent, proactive agent reachable via LINE, replacing the current `claude -p` subprocess architecture in raise-a-bull with a simpler, more capable model.

---

## Design Principles

1. **Upstream-clean** — The plugin is standalone. No raise-a-bull dependencies. Any Claude Code user can use it independently. Contribution via Anthropic's [plugin directory submission form](https://clau.de/plugin-directory-submission).
2. **Zero-config tunnel** — Default startup spawns a quick cloudflared tunnel and auto-sets the LINE webhook URL. No DNS, no Cloudflare account, no manual webhook config.
3. **Try reply, fall back to push** — Use reply token first (free). If it fails (expired), fall back to push API (costs quota). No timestamp tracking.
4. **Always respond** — Unknown users and unenabled groups get a helpful response with their ID, never silence.
5. **Modular split** — `server.ts` (MCP + tools), `line.ts` (LINE platform adapter), `access.ts` (access control logic). Clean separation for readability, testability, and future reuse.

---

## Architecture: The Paradigm Shift

### `claude -p` (current raise-a-bull) = Request/Response Bot

```
LINE → FastAPI → claude -p "{msg}" --resume {session} → parse stream-json → reply
```

Process spawns per message, exits after responding. Claude only speaks when spoken to.

### `--channels` (this plugin) = Persistent Living Agent

```
Claude Code (persistent session)
  ├── LINE plugin (MCP server) — messaging transport
  ├── Other MCP tools — web search, CDN, etc.
  └── Future: heartbeat service, file watchers, calendar
```

Claude is alive between messages. It can:
- Receive messages and reply (reactive)
- Receive heartbeats and proactively reach out (future)
- Monitor files and notice changes
- Use MCP tools continuously
- Coordinate across multiple channels (LINE + Discord in one session)

### What raise-a-bull becomes (future, not this spec)

```
Before: raise-a-bull = engine + context + messaging + deployment
After:  raise-a-bull = context + heartbeat + toolbox
        LINE plugin  = messaging (standalone, upstream-able)
```

raise-a-bull subtracts to: identity (who am I), memory (what do I remember), capabilities (what tools do I have), and schedule (when should I check in). The messaging transport is just a plugin. This refactoring happens after the plugin is proven.

---

## Plugin Structure

```
plugins/line/
├── .claude-plugin/
│   └── plugin.json          # name: "claude-channel-line"
├── .mcp.json                # {"line": {"command": "bun", "args": [...]}}
├── server.ts                # MCP server, access control, tools, message chunking
├── line.ts                  # Bun HTTP server, webhook, LINE API, auto-tunnel
├── package.json             # @modelcontextprotocol/sdk, @line/bot-sdk
├── README.md                # Setup guide
├── ACCESS.md                # Access control docs
├── skills/
│   ├── access/              # /line:access pair, allow, deny, list
│   └── configure/           # /line:configure token, tunnel
├── LICENSE                  # Apache 2.0
└── bun.lock
```

### File Responsibilities

**`server.ts`** — Generic channel plugin skeleton:
- MCP server init (stdio transport, `experimental: { 'claude/channel': {} }`)
- Access control: read/write `access.json`, pairing codes, gate function
- Tool handlers: `reply`, `push_message`, `get_profile`
- Message chunking: split long text at LINE's 5000-char limit
- Skill definitions: `/line:access`, `/line:configure`
- Imports and starts the LINE transport from `line.ts`

**`line.ts`** — LINE platform adapter:
- Bun HTTP server listening on configurable port
- Webhook signature verification (`validateSignature` from `@line/bot-sdk`)
- Parse LINE webhook events (message, follow, join, etc.)
- LINE `MessagingApiClient` (replyMessage, pushMessage, getProfile)
- Reply token cache (try reply first, fall back to push)
- Auto-tunnel: spawn cloudflared, parse URL, call `setWebhookEndpointUrl`
- Export: `startLineServer(callbacks)`

### Launch

```bash
claude --channels plugin:line
```

---

## Auto-Tunnel & Webhook Setup

LINE requires an HTTP endpoint reachable from the internet. The plugin handles this automatically.

### Startup Sequence

```
Plugin starts (MCP stdio connected to Claude Code)
  │
  ├─ 1. Start Bun HTTP server on localhost:{port}
  │     Default port: 3000 (configurable via --port or LINE_PORT env)
  │
  ├─ 2. Spawn cloudflared quick tunnel
  │     $ cloudflared tunnel --url http://localhost:{port}
  │     Parse stderr for trycloudflare.com URL (cloudflared prints to stderr)
  │     Timeout after 15s if no URL found
  │
  ├─ 3. Call LINE API: setWebhookEndpointUrl
  │     Sets webhook to https://{random}.trycloudflare.com/webhook
  │
  ├─ 4. Verify webhook
  │     POST testWebhookEndpoint — confirm LINE can reach us
  │
  └─ 5. Ready — log webhook URL, accept messages
```

### Tunnel Options

| User | Setup | Command |
|------|-------|---------|
| Normal | Zero config | `claude --channels plugin:line` |
| Power user | Own domain | `claude --channels plugin:line -- --tunnel-url https://bot.pwlee.xyz` |
| Docker/infra | Port already exposed | `claude --channels plugin:line -- --no-tunnel --port 8000` |

- **Default: quick tunnel** — URL changes on restart, but `setWebhookEndpoint` auto-updates it. User never touches Cloudflare.
- **`--tunnel-url URL`** — skip cloudflared, use provided URL (for named tunnels, ngrok, etc.)
- **`--no-tunnel`** — skip tunnel entirely (port already exposed via reverse proxy, Docker, etc.)
- **cloudflared must be pre-installed** — clear error with install instructions if missing

### Shutdown

Kill cloudflared subprocess on process exit (SIGTERM/SIGINT handler).

### Error Cases

- cloudflared not installed → error: "Install cloudflared: `brew install cloudflared`"
- Tunnel fails to start → error, suggest `--tunnel-url` or `--no-tunnel`
- `setWebhookEndpointUrl` fails → likely bad access token, clear error
- Webhook test fails → tunnel URL not reachable, retry once

---

## Tools & Message Flow

### Inbound (LINE → Claude)

```
LINE Platform → POST /webhook (signature verified via @line/bot-sdk)
  │
  ├─ gate(event) — check access control
  │   ├─ Allowed → send MCP notification
  │   ├─ Unknown DM (pairing) → reply with pairing code + user_id
  │   ├─ Unknown DM (allowlist) → reply with user_id + instructions
  │   └─ Unknown group → reply with group_id + instructions
  │
  └─ mcp.notification({
       method: 'notifications/claude/channel',
       params: {
         content: "message text",
         meta: {
           chat_id: "U1234..." (user) or "C1234..." (group),
           message_id: event.message.id,
           user: display name,
           user_id: LINE user ID,
           ts: ISO8601,
           message_type: "text" | "image" | "sticker" | "location"
         }
       }
     })
```

### Outbound Tools (Claude → LINE)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `reply` | `chat_id`, `text`, `reply_to` | Send message in response to a user. `reply_to` is the `message_id` from the inbound notification. Try reply token first → if fails → push API |
| `push_message` | `chat_id`, `text` | Always uses push API. For proactive/unsolicited messages where there's no recent inbound event. |
| `get_profile` | `user_id` | Get user's display name and profile picture URL |

### Reply Token Handling

Reply tokens are per-event, not per-chat. The cache maps `message_id → { chat_id, reply_token }`. Multiple rapid messages each keep their own token — no overwrites.

The `reply` tool requires `reply_to: message_id` to pair the response with a specific inbound message's token. This avoids unpredictable behavior from using the wrong token.

```
reply(chat_id, text, reply_to)
  ├─ Have cached reply_token for reply_to?
  │   ├─ Yes → try replyMessage(token, text)
  │   │         ├─ Success → done (free, no quota)
  │   │         └─ Fail (expired) → pushMessage(chat_id, text)
  │   └─ No → pushMessage(chat_id, text)
  └─ Remove reply_to from token cache
```

No timestamp tracking. Let LINE tell us if the token is expired.

### No `fetch_messages`

LINE API doesn't support fetching message history (same limitation as Telegram).

### Message Types (v1)

- **Inbound text:** forwarded as-is in notification `content`
- **Inbound image:** Depends on `contentProvider.type`:
  - `"line"` (user-sent, most common): No URLs in webhook. Call `MessagingApiBlob.getMessageContent(messageId)` to download binary, save to `~/.claude/channels/line/inbox/`, pass local file path in notification `content` (e.g., `"(image: /path/to/inbox/msg123.jpg)"`)
  - `"external"`: URLs provided directly (`originalContentUrl`, `previewImageUrl`). Pass URL in notification `content`.
- **Inbound sticker:** forward sticker package + sticker ID in `content`
- **Inbound location:** forward title + address + lat/lng in `content`
- **Outbound:** text only. Rich messages (Flex, template, image replies) deferred to future.

---

## Access Control

Following the Discord/Telegram pairing pattern.

### State File

`~/.claude/channels/line/access.json`

```json
{
  "dms": {
    "policy": "pairing",
    "allowlist": ["U1234abcd..."],
    "pairing": {
      "a3f2c1": { "user_id": "U5678...", "expires": "2026-03-20T12:30:00Z" }
    }
  },
  "groups": {
    "C9876...": { "enabled": true, "requireMention": true }
  }
}
```

### DM Policies

- **Pairing (default):** Unknown user → bot replies with 6-char hex code + user ID + instructions
- **Allowlist:** Unknown user → bot replies with user ID + "contact bot owner"
- **Disabled:** All DMs silently dropped

### Group Access

Opt-in by group/room ID. Unenabled groups get a response with their group ID and instructions.

**Message filtering in enabled groups:** Default is `requireMention: true` — only messages that @mention the bot are forwarded to Claude. This prevents the bot from being noisy in group chats.

Configurable per group:
- **`requireMention: true`** (default): Only messages that @mention the bot are forwarded.
- **`triggerPrefix`** (e.g., `"小助理"`): Only messages starting with the prefix are forwarded. The prefix is stripped before forwarding. Overrides `requireMention`.
- **`requireMention: false`** + no prefix: All messages forwarded (use with caution in active groups).
- **DMs always forward** — no filter in personal chats (same as current raise-a-bull behavior).

**Leave/unfollow events:** When the bot is removed from a group or a user blocks the bot, the plugin logs the event but does NOT auto-remove from `access.json`. Stale entries are harmless — messages simply stop arriving.

### Gate Function

```
Incoming message
  ├─ From DM?
  │   ├─ User in allowlist → forward to Claude (always, no prefix filter)
  │   ├─ Pairing mode → reply with code + user_id + instructions
  │   └─ Allowlist mode → reply with user_id + instructions
  │
  └─ From group?
      ├─ Group not enabled → reply with group_id + instructions
      └─ Group enabled
          ├─ triggerPrefix set → starts with prefix? strip prefix, forward
          ├─ No prefix → requireMention (default true) → @mentions bot? forward
          ├─ requireMention: false + no prefix → forward all
          └─ Doesn't match filter → silently ignore
```

No silent drops (except DM disabled policy). Everyone gets a helpful response with their ID so the owner can allow them immediately.

### Response Templates

**DM — pairing mode:**
> "Hi! Pairing code: `a3f2c1`
> Your user ID: `U1234abcd...`
> Ask the bot owner to run `/line:access pair a3f2c1` in Claude Code."

**DM — allowlist mode:**
> "I'm not set up to chat with you yet.
> Your user ID: `U1234abcd...`
> Ask the bot owner to run `/line:access allow U1234abcd...`"

**Group — not enabled:**
> "I'm not enabled for this group yet.
> Group ID: `C9876efgh...`
> Owner: run `/line:access allow C9876efgh...`"

### Skills

- `/line:access pair CODE` — approve a pairing request
- `/line:access allow ID` — add user or group to allowlist
- `/line:access deny ID` — remove from allowlist
- `/line:access list` — show allowlist and pending pairings
- `/line:configure token` — set LINE channel access token + secret
- `/line:configure tunnel` — set custom tunnel URL

---

## Configuration & Secrets

### Token Storage

`~/.claude/channels/line/.env`

```
LINE_CHANNEL_SECRET=xxx
LINE_CHANNEL_ACCESS_TOKEN=xxx
```

### First Run Flow

1. User runs `claude --channels plugin:line`
2. No `.env` found → plugin prompts: "Run `/line:configure token` to set up"
3. `/line:configure token` skill guides user to enter channel secret + access token
4. Written to `~/.claude/channels/line/.env` with chmod 600

### File Layout

```
~/.claude/channels/line/
├── .env              # Secrets (chmod 600)
├── access.json       # Allowlist, pairing state, group config
└── inbox/            # Downloaded images/files from LINE
```

### Environment Variable Override

If `LINE_CHANNEL_SECRET` and `LINE_CHANNEL_ACCESS_TOKEN` are already set as environment variables (e.g., in Docker), skip `.env` file. Env vars take precedence.

---

## Onboarding Flows

### Standalone (any Claude Code user)

```
$ claude --channels plugin:line
> "No LINE credentials found. Run /line:configure token to set up."
$ /line:configure token
> (guides through LINE Developer Console, paste secret + token)
> "Configured. Starting tunnel..."
> "Webhook active at https://xxx.trycloudflare.com/webhook"
> "Send a message to your bot on LINE to test!"
```

### raise-a-bull (future, not this spec)

```
$ bash raise_bull.sh mybot
  ├─ build_barn.sh (install deps including cloudflared)
  ├─ Create workspace/identity via gum TUI
  ├─ Collect LINE secrets via gum
  ├─ Configure LINE plugin credentials
  └─ claude --channels plugin:line (with workspace context)
```

The TUI is raise-a-bull's job, not the plugin's. The plugin is self-sufficient with its skill-based setup.

---

## Session Management

### v1: Single Shared Session

All chats (DMs and groups) share one Claude Code conversation context. Claude distinguishes chats by `chat_id` in notifications and tool calls.

- **For personal use (1-2 chats):** This is a feature, not a limitation. Claude has full cross-chat context.
- **For many unrelated chats:** Context from different conversations may bleed. Claude Code auto-compresses old messages as context fills.

### Future: Per-Chat Session Routing

When single-session becomes a limitation:
- Primary chat (paired) → persistent `--channels` session
- Secondary chats → plugin spawns `claude -p --resume {id}` per message
- Plugin handles routing internally based on chat_id

This is a future enhancement, not in v1.

---

## Known Limitations (v1)

- **Single session** — all chats share one Claude Code context
- **Text-only outbound** — replies are text only, no Flex/template/image
- **Quick tunnel only by default** — URL changes on restart (auto-updated via API)
- **No `fetch_messages`** — LINE API doesn't support it
- **cloudflared required** — must be pre-installed for default tunnel flow
- **No heartbeat** — future agents-infra service, separate from this plugin

---

## Future Enhancements (not in this spec)

- **Heartbeat service** — agents-infra hosted MCP server with web config, API keys, and schedule management
- **Per-chat session routing** — main chat uses `--channels`, others use `claude -p --resume`
- **Rich outbound messages** — Flex messages, image replies, quick reply buttons
- **Named tunnel support** — deeper Cloudflare integration for persistent domains
- **raise-a-bull refactor** — subtract to context + toolbox layer after plugin is proven
- **Multi-channel** — LINE + Discord in same Claude Code session
- **Relay server** — shared webhook relay via agents-infra for cloud-hosted bots

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `@modelcontextprotocol/sdk` | MCP server + stdio transport |
| `@line/bot-sdk` | LINE API client + webhook signature verification |
| `bun` | Runtime, HTTP server, package manager |

No framework dependencies (no Express, no Hono). Bun's native HTTP server handles webhooks.

---

## Security

| Rule | Enforcement |
|------|-------------|
| Secrets never in chat | Stored in `~/.claude/channels/line/.env` (chmod 600) |
| Webhook signature verified | `validateSignature` from `@line/bot-sdk` on every request. Return 200 on all requests (LINE retries on non-200) |
| Access control on every message | Gate function checks allowlist before forwarding |
| No file exfiltration | Outbound file paths validated, `.env`/`access.json` blocked |
| Pairing codes expire | 1-hour TTL on pairing codes |

---

## Files to Create

| File | Location |
|------|----------|
| `server.ts` | `plugins/line/server.ts` |
| `line.ts` | `plugins/line/line.ts` |
| `plugin.json` | `plugins/line/.claude-plugin/plugin.json` |
| `.mcp.json` | `plugins/line/.mcp.json` |
| `package.json` | `plugins/line/package.json` |
| `README.md` | `plugins/line/README.md` |
| `ACCESS.md` | `plugins/line/ACCESS.md` |
| `skills/access/SKILL.md` | `plugins/line/skills/access/SKILL.md` |
| `skills/configure/SKILL.md` | `plugins/line/skills/configure/SKILL.md` |
| `LICENSE` | `plugins/line/LICENSE` |
