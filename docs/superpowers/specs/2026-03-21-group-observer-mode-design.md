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
  autoFlush?: 'discard' | 'forward'  // default: 'forward'
}
```

- `mode` controls whether non-triggered messages are dropped or buffered.
- `autoFlush` controls what happens when buffered messages expire (60-min TTL) without a trigger. Defaults to `'forward'` so Claude always gets context. Configurable per-group.

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
- **Max buffer size:** 200 messages per group. When the cap is hit, behavior follows the group's `autoFlush` setting: `'forward'` (default) flushes all 200 as an auto-flush notification and continues buffering fresh messages; `'discard'` drops the oldest message to make room. This keeps the `autoFlush` knob consistent across both TTL expiry and cap-hit.
- **Display names** are resolved at push time (in `handleInbound`, before buffering) since the user context is available then.

**TTL:** 60 minutes. Chosen to capture a full conversation window. If the process crashes, the buffer is lost — acceptable tradeoff to avoid premature disk persistence.

**Existing configs:** Groups without `mode` or `autoFlush` fields require no migration — both default to `'filtered'` and `'forward'` respectively via code-level defaults.

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
- MCP notification meta includes `chat_id` (so Claude knows where to `push_message`) but no `message_id` or `reply_to`.
- Security suffix is appended after the context block.

**Non-text messages in buffer:** Buffered messages use the same `formatInboundContent()` output already used for filtered mode (e.g., `(sticker: ...)`, `(image: ...)`). No special handling needed.

### 5. Filter Function & Flow

All mode branching lives inside `shouldForwardGroupMessage`. The function already has access to `config.groups[groupId]`, so it reads `mode` from there. `server.ts` just acts on the result.

**Updated `FilterResult`:**

```typescript
export interface FilterResult {
  forward: boolean
  buffer?: boolean   // true = buffer this message (observer mode)
  text?: string
}
```

**`shouldForwardGroupMessage` logic:**

```
Is group enabled? No → { forward: false }

What mode? (default: 'filtered')

  "filtered":
    → Current logic, unchanged (prefix → mention → forward-all)

  "observer":
    Has triggerPrefix?
      YES, message matches prefix → { forward: true, text: stripped }
      YES, message doesn't match → { forward: false, buffer: true }
    No triggerPrefix, requireMention?
      YES, is mention → { forward: true, text }
      YES, not mention → { forward: false, buffer: true }
    Neither trigger set → { forward: true, text }  (every msg is trigger)
```

**Key: prefix still takes absolute priority in observer mode.** When `triggerPrefix` is set, a @mention that doesn't match the prefix returns `{ forward: false, buffer: true }` — it gets buffered, not forwarded. This preserves the existing precedence where prefix overrides mention.

**`server.ts` flow (simplified):**

```
result = shouldForwardGroupMessage(...)
if result.forward → flush buffer + trigger → send notification
else if result.buffer → push to buffer
else → drop (filtered mode)
```

**Constraint:** Observer mode requires at least one trigger mechanism — either `requireMention: true` (default) or a `triggerPrefix`. If a group has `mode: 'observer'` with `requireMention: false` and no `triggerPrefix`, every message is a trigger and the buffer flushes immediately, making it identical to "forward all." The function treats this as valid (not an error) but the docs should warn that this combination makes observer mode pointless.

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
- Buffer cap (200) with `autoFlush: 'forward'` triggers auto-flush notification
- Buffer cap (200) with `autoFlush: 'discard'` drops oldest messages

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
| `server.ts` | Extract `handleInbound` for testability; buffer logic; cleanup interval; `formatObserverNotification()` helper (shared by trigger-flush and auto-flush paths) |
| `ACCESS.md` | Document observer mode, exact field names |
| `skills/access/SKILL.md` | Add `set` command, explicit field names, `--observer` flag |
| `__tests__/message-buffer.test.ts` | New — buffer unit tests |
| `__tests__/gate-filter.test.ts` | Add observer mode filter tests |
| `__tests__/observer-integration.test.ts` | New — integration tests |
