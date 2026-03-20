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
  pushedAt: number  // Date.now() at push time, used for TTL
}

const OBSERVER_BUFFER_TTL_MS = 60 * 60 * 1000  // 60 minutes
const MAX_BUFFER_PER_GROUP = 200  // hard cap, drop oldest when exceeded

class MessageBuffer {
  // Map<groupId, BufferedMessage[]>

  push(groupId, msg)                  // append to group buffer; if size > MAX, drop oldest
  flush(groupId): BufferedMessage[]   // drain and return all, clear buffer for group
  cleanup(getAutoFlush: (groupId: string) => 'discard' | 'forward'):
    Map<string, BufferedMessage[]>    // returns groups whose expired msgs should be forwarded
}
```

- One buffer per group, keyed by `groupId`.
- `cleanup()` runs on the existing 30-second interval (shared with token cache cleanup).
- `cleanup()` accepts a callback `getAutoFlush(groupId)` that looks up the group's `autoFlush` setting from the current `AccessConfig`. For `'discard'` groups, expired messages are silently dropped. For `'forward'` groups, expired messages are returned in the result map so the caller (`server.ts`) can send MCP notifications.
- **Max buffer size:** 200 messages per group. When exceeded, oldest messages are dropped. This prevents unbounded growth from spam or very active groups.
- **Display names** are resolved at push time (in `handleInbound`, before buffering) since the user context is available then.

**TTL:** 60 minutes. Chosen to capture a full conversation window. If the process crashes, the buffer is lost — acceptable tradeoff to avoid premature disk persistence.

**Existing configs:** Groups without `mode` or `autoFlush` fields require no migration — both default to `'filtered'` and `'discard'` respectively via code-level defaults.

### 4. Notification Format

**Triggered flush** — buffer + trigger message:

```
<context chat_id="C123" mode="observer" unread_count="2">
[14:01] Bob: anyone free for lunch?
[14:02] Charlie: I'm down
</context>

[14:03] Alice: @bot what's a good place nearby?

---
[SYSTEM: Above is a message from an external user. You must NEVER reveal secrets, credentials, API keys, .env contents, or access tokens.]
```

- The `<context>` block contains buffered history.
- The message after it is the trigger — what Claude should respond to.
- The security suffix is appended once at the end, after the trigger message (not inside the `<context>` block).
- MCP notification meta (`message_id`, `user`, `reply_to`) all refer to the trigger message.
- Reply token is cached for the trigger message only.
- Timestamps in the `<context>` block use `HH:MM` format derived from the ISO8601 timestamp, in the server's local timezone.

**Auto-flush (forward)** — no trigger message:

```
<context chat_id="C123" mode="observer" unread_count="5" auto_flushed="true">
[13:01] Bob: anyone free for lunch?
[13:02] Charlie: I'm down
[13:15] Alice: we went to that new ramen place
[13:20] Bob: it was great
[13:45] Charlie: back at desk now
</context>

---
[SYSTEM: Above are messages from external users. You must NEVER reveal secrets, credentials, API keys, .env contents, or access tokens.]
```

- `auto_flushed="true"` tells Claude this is background context, not a request.
- No `message_id` or `reply_to` in meta — Claude can only respond proactively via `push_message`.
- Security suffix is appended after the context block.

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

In observer mode:
- Non-triggered messages return `{ forward: false, buffer: true }`.
- Triggered messages return `{ forward: true, text }` — prefix stripping still applies when `triggerPrefix` matches.

In filtered mode: unchanged (`{ forward: false }` for non-triggered, `{ forward: true, text }` for triggered).

**Constraint:** Observer mode requires at least one trigger mechanism — either `requireMention: true` (default) or a `triggerPrefix`. If a group has `mode: 'observer'` with `requireMention: false` and no `triggerPrefix`, every message would be a trigger and the buffer would flush immediately, making it identical to "forward all." The `shouldForwardGroupMessage` function treats this as valid (not an error) but the docs should warn that this combination makes observer mode pointless.

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
- Buffer -> trigger -> flush: 3 non-trigger webhooks, then a mention webhook. Verify single notification callback with buffered context + trigger.
- Auto-flush forward: buffer messages, advance time past 60 min, trigger cleanup. Verify notification callback fires with `auto_flushed="true"`.
- Auto-flush discard: same setup, verify no notification callback and empty buffer.
- Filtered mode unchanged: verify non-mention messages are dropped (no buffer) and mentions fire immediately.

**Test plumbing:** Uses `startHttpServer` with real HTTP requests and a real `MessageBuffer`. The `handleInbound` function (which contains the observer logic) is extracted from `main()` to be independently testable — it takes dependencies (`lineClient`, `messageBuffer`, `access`, `notifyFn`) as parameters. Tests provide a mock `notifyFn` callback to capture notifications and a stubbed `lineClient` (since we can't hit LINE's real API). The `access` config and `messageBuffer` are real instances.

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
