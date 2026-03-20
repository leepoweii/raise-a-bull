---
name: access
description: Manage LINE channel access control — pair users, allow/deny, configure groups
---

## Commands

### `/line:access pair <CODE>`
Approve a pairing request. The code is shown to users who message the bot for the first time.

### `/line:access allow <ID>`
Add a user ID or group ID to the allowlist.
- User IDs start with `U` (e.g., `U1234abcd...`)
- Group IDs start with `C` (e.g., `C9876efgh...`)
- To enable observer mode, follow up with `/line:access set <GROUP_ID> mode observer`

### `/line:access deny <ID>`
Remove a user or disable a group.

### `/line:access set <GROUP_ID> <field> <value>`
Set a group config field. Fields and their exact JSON names:
- `mode` — `"filtered"` (default) or `"observer"`
- `autoFlush` — `"forward"` (default) or `"discard"`
- `triggerPrefix` — e.g., `"CC"` (use `""` to clear)
- `requireMention` — `true` (default) or `false`

### `/line:access list`
Show current allowlist, enabled groups (with mode/settings), and pending pairing codes.

## Notes

Access state is stored in `~/.claude/channels/line/access.json`.

### Group Config JSON Field Names

When writing to `access.json`, use these exact field names:
```json
{
  "enabled": true,
  "requireMention": true,
  "triggerPrefix": "CC",
  "mode": "observer",
  "autoFlush": "forward"
}
```
