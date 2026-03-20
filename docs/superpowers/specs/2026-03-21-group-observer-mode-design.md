# Group Observer Mode Design

**Date:** 2026-03-21
**Branch:** `feat/line-channel-plugin`
**Scope:** `plugins/line/`

## Problem

The LINE channel plugin's group message handling has three issues:

1. **Field naming mismatch** — The access skill doesn't document exact JSON field names, causing Claude to write `prefix` instead of `triggerPrefix` when configuring groups.

2. **No conversation context** — In filtered mode, Claude only sees triggered messages (mentions/prefix matches). It has no context of the surrounding conversation, making responses feel disconnected.

3. **Binary behavior** — Groups are either "forward everything" or "filter strictly." There's no middle ground where Claude can observe the conversation and respond intelligently when triggered.

## Solution

### 1. Observer Mode

Add a per-group `mode` field to `GroupConfig`:

- **`filtered`** (default, current behavior) — Messages are dropped at the code level unless they match the trigger (mention or prefix). Claude never sees non-triggered messages.
- **`observer`** — All messages are buffered in memory. When a trigger arrives (mention or prefix), the buffer is flushed as conversation context alongside the trigger message in a single notification.

### 2. GroupConfig Type

```typescript
export interface GroupConfig {
  enabled: boolean
  requireMention: boolean
  triggerPrefix?: string
  mode?: 'filtered' | 'observer'     // default: 'filtered'
  autoFlush?: 'discard' | 'forward'  // default: 'discard'
}
```

- `mode` controls whether non-triggered messages are dropped or buffered.
- `autoFlush` controls what happens when buffered messages expire (60-min TTL) without a trigger. Configurable per-group.

### 3. Message Buffer

New file: `plugins/line/message-buffer.ts`

```typescript
interface BufferedMessage {
  userId: string
  displayName: string
  text: string
  messageType: string
  timestamp: string
}

class MessageBuffer {
  // Map<groupId, BufferedMessage[]>

  push(groupId, msg)                  // append to group buffer
  flush(groupId): BufferedMessage[]   // drain and return all
  cleanup()                           // handle expired messages (>60 min)
}
```

- One buffer per group, keyed by `groupId`.
- `cleanup()` runs on the existing 30-second interval (shared with token cache cleanup).
- On cleanup, expired messages are either silently discarded or forwarded as a notification, depending on the group's `autoFlush` setting.

**TTL:** 60 minutes. Chosen to capture a full conversation window. Memory impact is negligible (~100KB for a very active group). If the process crashes, the buffer is lost — acceptable tradeoff to avoid premature disk persistence.

```typescript
const OBSERVER_BUFFER_TTL_MS = 60 * 60 * 1000
```

### 4. Notification Format

**Triggered flush** — buffer + trigger message:

```
<context chat_id="C123" mode="observer" unread_count="2">
[14:01] Bob: anyone free for lunch?
[14:02] Charlie: I'm down
</context>

[14:03] Alice: @bot what's a good place nearby?
```

- The `<context>` block contains buffered history.
- The message after it is the trigger — what Claude should respond to.
- MCP notification meta (`message_id`, `user`, `reply_to`) all refer to the trigger message.
- Reply token is cached for the trigger message only.

**Auto-flush (forward)** — no trigger message:

```
<context chat_id="C123" mode="observer" unread_count="5" auto_flushed="true">
[13:01] Bob: anyone free for lunch?
[13:02] Charlie: I'm down
[13:15] Alice: we went to that new ramen place
[13:20] Bob: it was great
[13:45] Charlie: back at desk now
</context>
```

- `auto_flushed="true"` tells Claude this is background context, not a request.
- No `message_id` or `reply_to` in meta — Claude can only respond proactively via `push_message`.

### 5. Flow Changes in `server.ts`

```
Group message arrives
  -> Is group enabled? (unchanged)
  -> What mode?

    "filtered" (default):
      -> Current behavior, unchanged

    "observer":
      -> Is this a trigger? (mention or prefix match)
        YES -> flush buffer + format trigger -> single notification -> send
        NO  -> push to buffer, return (no notification)
```

### 6. Filter Return Type Update

`shouldForwardGroupMessage` needs to distinguish between "drop" and "buffer":

```typescript
export interface FilterResult {
  forward: boolean
  buffer?: boolean   // true = buffer this message (observer mode)
  text?: string
}
```

In observer mode, non-triggered messages return `{ forward: false, buffer: true }`. In filtered mode, non-triggered messages return `{ forward: false }` as before.

### 7. Skill & Docs Updates

**`skills/access/SKILL.md`** — Add explicit JSON field names and new commands:

- `/line:access allow <ID> [--observer]` — enable observer mode on group add
- `/line:access set <GROUP_ID> <field> <value>` — set config fields (`mode`, `autoFlush`, `triggerPrefix`, `requireMention`)

**`ACCESS.md`** — Document observer mode, auto-flush behavior, and exact JSON field names for group config.

### 8. Testing

**Unit tests: `__tests__/message-buffer.test.ts`** (new)
- `push()` adds messages to correct group
- `flush()` returns messages in order and clears the buffer
- `flush()` on empty/unknown group returns `[]`
- `cleanup()` with `discard` drops expired messages silently
- `cleanup()` with `forward` returns expired messages for notification
- Messages within TTL are not cleaned up
- Multiple groups buffer independently

**Unit tests: `__tests__/gate-filter.test.ts`** (update)
- Observer mode returns `{ forward: false, buffer: true }` for non-triggered messages
- Observer mode returns `{ forward: true }` for triggered messages (mention/prefix)
- Filtered mode unchanged

**Integration tests: `__tests__/observer-integration.test.ts`** (new)
- Buffer -> trigger -> flush: 3 non-trigger webhooks, then a mention webhook. Verify single notification with buffered context + trigger.
- Auto-flush forward: buffer messages, advance time past 60 min, trigger cleanup. Verify notification fires with `auto_flushed="true"`.
- Auto-flush discard: same setup, verify no notification and empty buffer.
- Filtered mode unchanged: verify non-mention messages are dropped (no buffer) and mentions fire immediately.

Uses `startHttpServer` directly with real HTTP requests. Only `lineClient` (external LINE API) is stubbed.

## Files Changed

| File | Change |
|------|--------|
| `access.ts` | Add `mode`, `autoFlush` to `GroupConfig`; add `buffer` to `FilterResult`; update `shouldForwardGroupMessage` |
| `message-buffer.ts` | New — `MessageBuffer` class |
| `server.ts` | Buffer logic in `handleInbound`, cleanup interval, flush formatting |
| `ACCESS.md` | Document observer mode, exact field names |
| `skills/access/SKILL.md` | Add `set` command, explicit field names, `--observer` flag |
| `__tests__/message-buffer.test.ts` | New — buffer unit tests |
| `__tests__/gate-filter.test.ts` | Add observer mode filter tests |
| `__tests__/observer-integration.test.ts` | New — integration tests |
