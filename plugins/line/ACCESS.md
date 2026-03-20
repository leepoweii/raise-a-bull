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

### Group Modes

#### Filtered (default)
Messages that don't match a trigger (mention or prefix) are silently dropped. Claude only sees triggered messages.

#### Observer
All messages are buffered in memory. When a trigger arrives, Claude receives the buffered conversation context alongside the trigger message in a single notification. This lets Claude understand the conversation before responding.

Enable observer mode: `/line:access set <GROUP_ID> mode observer`

### Message Filtering

Both modes use the same trigger rules:

- **`requireMention: true`** (default) — Only @mentions trigger the bot
- **`triggerPrefix`** (e.g., `"CC"`) — Only messages starting with the prefix trigger the bot. The prefix is stripped from the forwarded text. Takes priority over `requireMention`.
- **`requireMention: false`** + no prefix — All messages trigger (observer mode becomes equivalent to "forward all")

### Auto-Flush (Observer Mode)

When buffered messages expire (60-min TTL) or the buffer cap (200 messages) is hit:

- **`autoFlush: "forward"`** (default) — Expired/capped messages are sent to Claude as background context
- **`autoFlush: "discard"`** — Expired/capped messages are silently dropped

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
      "requireMention": true,
      "triggerPrefix": "CC",
      "mode": "observer",
      "autoFlush": "forward"
    }
  }
}
```

## Commands

- `/line:access pair <CODE>` — Approve pairing
- `/line:access allow <ID>` — Add user/group
- `/line:access deny <ID>` — Remove user/disable group
- `/line:access set <GROUP_ID> <field> <value>` — Set group config field
- `/line:access list` — Show current state
