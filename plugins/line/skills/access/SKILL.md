---
name: access
description: Manage LINE channel access control — pair users, allow/deny, configure groups
---

All commands read and write `~/.claude/channels/line/access.json`. Read the file first, modify the JSON, then write it back.

## Commands

### `/line:access pair <CODE>`
Approve a pairing request.

**Steps:**
1. Read `~/.claude/channels/line/access.json`
2. Find `dms.pairing[CODE]` — if it exists and hasn't expired, move `user_id` to `dms.allowlist`
3. Delete the pairing entry
4. Write the file back
5. Confirm to the user

### `/line:access allow <ID>`
Add a user ID or group ID to the allowlist.

**Steps:**
1. Read `~/.claude/channels/line/access.json`
2. If ID starts with `C` or `R` (group/room): set `groups[ID] = { "enabled": true, "requireMention": true }` (preserve existing fields if group already exists, just set `enabled: true`)
3. If ID starts with `U` (user): add to `dms.allowlist` array (skip if already present)
4. Write the file back
5. Confirm to the user

### `/line:access deny <ID>`
Remove a user or disable a group.

**Steps:**
1. Read `~/.claude/channels/line/access.json`
2. If ID starts with `C` or `R`: set `groups[ID].enabled = false`
3. If ID starts with `U`: remove from `dms.allowlist` array
4. Write the file back
5. Confirm to the user

### `/line:access set <GROUP_ID> <field> <value>`
Set a group config field.

**Valid fields and values:**
- `mode` — `"filtered"` (default) or `"observer"`
- `autoFlush` — `"forward"` (default) or `"discard"`
- `triggerPrefix` — any string, e.g., `"CC"` (use `""` to clear)
- `requireMention` — `true` (default) or `false`

**Steps:**
1. Read `~/.claude/channels/line/access.json`
2. Find `groups[GROUP_ID]` — if it doesn't exist, tell the user to run `/line:access allow <GROUP_ID>` first
3. Set `groups[GROUP_ID][field] = value` using the exact JSON field name above. Parse `true`/`false` as booleans, not strings. Parse `""` as removing the field (delete it from the object).
4. Write the file back
5. Confirm the change and show the updated group config

### `/line:access list`
Show current access state.

**Steps:**
1. Read `~/.claude/channels/line/access.json`
2. Display:
   - DM policy (`dms.policy`)
   - Allowlisted users (`dms.allowlist`)
   - Pending pairing codes (`dms.pairing`) — show code, user_id, and expiry
   - Enabled groups (`groups`) — show group ID, enabled status, mode, requireMention, triggerPrefix, autoFlush

## JSON Field Reference

When writing to `access.json`, use these exact field names for group config:
```json
{
  "enabled": true,
  "requireMention": true,
  "triggerPrefix": "CC",
  "mode": "observer",
  "autoFlush": "forward"
}
```
