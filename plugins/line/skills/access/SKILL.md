---
name: access
description: Manage LINE channel access control — pair users, allow/deny, list
---

## Commands

### `/line:access pair <CODE>`
Approve a pairing request. The code is shown to users who message the bot for the first time.

### `/line:access allow <ID>`
Add a user ID or group ID to the allowlist. Groups default to requireMention: true.
- User IDs start with `U` (e.g., `U1234abcd...`)
- Group IDs start with `C` (e.g., `C9876efgh...`)

### `/line:access deny <ID>`
Remove a user or disable a group.

### `/line:access list`
Show current allowlist, enabled groups, and pending pairing codes.

## Notes

Access state is stored in `~/.claude/channels/line/access.json`.
