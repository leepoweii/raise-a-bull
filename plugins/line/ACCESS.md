# Access Control

The LINE plugin controls who can communicate with your Claude Code session.

## DM Policies

### Pairing (default)
Unknown users receive a pairing code. You approve by running `/line:access pair <CODE>` in Claude Code.

### Allowlist
Unknown users are told they're not authorized and shown their user ID. You can add them with `/line:access allow <ID>`.

### Disabled
All DMs are silently dropped.

## Group Access

Groups are opt-in. When the bot is added to a group it hasn't been enabled for, it replies with the group ID and instructions.

### Message Filtering

Enabled groups have configurable message filtering:

- **`requireMention: true`** (default) — Only messages that @mention the bot are forwarded
- **`triggerPrefix`** (e.g., `"小助理"`) — Only messages starting with the prefix are forwarded. The prefix is stripped.
- **`requireMention: false`** + no prefix — All messages forwarded

DMs always forward without any filter.

## Configuration File

`~/.claude/channels/line/access.json`

```json
{
  "dms": {
    "policy": "pairing",
    "allowlist": ["U1234abcd..."],
    "pairing": {}
  },
  "groups": {
    "C9876efgh...": {
      "enabled": true,
      "requireMention": true
    }
  }
}
```

## Commands

- `/line:access pair <CODE>` — Approve pairing
- `/line:access allow <ID>` — Add user/group
- `/line:access deny <ID>` — Remove user/disable group
- `/line:access list` — Show current state
