# Session Management: Buffer + History + Nightly Compact — Design Spec

**Date:** 2026-04-06
**Status:** Approved

---

## Overview

Three features that work together to give the bot full conversation awareness and the dashboard full conversation visibility:

1. **Message Buffer** — Discord + LINE accumulate channel messages in SQLite. On @mention, buffer is injected as context into the prompt. After reply, buffer is hard-deleted (content graduates to Claude Code's .jsonl).
2. **Session History API** — Read Claude Code's .jsonl files to display full conversation history in the dashboard chat page.
3. **Nightly Compact + Consolidate** — Scheduled job compacts large sessions and consolidates learnings into memory files.

Plus two fixes: Heartbeat fresh start (no session persistence) and new settings (buffer_time, trigger_names).

---

## A1: Message Buffer (Discord)

### DB Schema

Add to sessions.db (via SessionStore.init migration):

```sql
CREATE TABLE IF NOT EXISTS message_buffer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_key TEXT NOT NULL,
    author TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    has_attachment INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_buffer_channel ON message_buffer(channel_key);
```

### Discord Bot Changes

**Every message** (whether mention or not):
- `INSERT INTO message_buffer (channel_key, author, content, timestamp)`
- Bot messages excluded (`if message.author.bot: return` already handles this)

**On @mention** (or during active timeout window):
1. `SELECT * FROM message_buffer WHERE channel_key = ? ORDER BY timestamp`
2. Split by `buffer_time` setting (default 10 minutes) — for **display grouping only**, all buffer messages are injected:
   - Older than buffer_time → grouped under "Earlier conversation" header
   - Within buffer_time → grouped under "Recent conversation" header
   - All messages are included verbatim (no truncation for typical workgroup volume)
3. Append current mention text as "User request"
4. Prepend current datetime for agent time awareness
5. `runner.run(combined_prompt, session_id=existing)`
6. After reply: `DELETE FROM message_buffer WHERE channel_key = ?`

### Three-tier Mode (unchanged logic, new buffer)

```
Silent  → accumulate to buffer (no LLM call)
Active  → accumulate to buffer + respond (LLM call)
Mention → accumulate to buffer + respond (LLM call) + enter active mode
```

### Prompt Format

```
現在時間：2026-04-06 14:30 (Sunday)

以下是頻道稍早的對話：
[14:00] Alice: 今天開會要討論什麼？
[14:01] Bob: 討論下週活動場地

---

以下是最近 10 分鐘的對話：
[14:05] Alice: 場地要先預約嗎
[14:26] Bob: 對，要先問社區

---

用戶提到你：
[14:30] Alice: 幫我整理一下剛才的討論重點
```

### Datetime Injection

Every prompt (on @mention or active-mode response) starts with:
```
現在時間：{YYYY-MM-DD HH:MM} ({weekday})
```
This gives the agent time awareness for scheduling, deadlines, and contextual responses. Uses the server's timezone (Asia/Taipei).

---

## A1b: Message Buffer (LINE)

Same as Discord but with LINE-specific trigger detection.

### Trigger Detection

LINE uses native @mention (SDK v3 `mention.mentionees[].is_self == True`). No prefix fallback needed.

```python
def line_bot_is_mentioned(event: MessageEvent) -> bool:
    msg = event.message
    if not isinstance(msg, TextMessageContent):
        return False
    if msg.mention and msg.mention.mentionees:
        for m in msg.mention.mentionees:
            if getattr(m, "is_self", False):
                return True
    return False
```

### LINE Webhook Changes

Currently: every TextMessageContent triggers LLM call.

New behavior for group chats:
- Non-mention text → buffer only (no LLM)
- @mention text → buffer + three-segment prompt + LLM response
- Active mode after mention → respond to all messages for `auto_reply_timeout` seconds

For DMs (1:1): behavior unchanged — always respond (no buffering needed).

### Image/File Messages in Buffer

When image/file arrives without mention:
- Store in buffer with `has_attachment=1` and content = "(image)" or "(file: filename.ext)"
- If followed by @mention: buffer context includes "(用戶上傳了圖片)" hints
- The actual attachment processing (parser → workspace/uploads/) only happens on mention trigger

---

## A2: Session History API

### Endpoint

`GET /api/chat/{session_id}/history`

### Implementation

1. Look up `session_id` (Claude Code UUID) from sessions DB using the session key
2. Find `.jsonl` file at: `/home/bull/.claude/projects/-app-workspace/{session_id}.jsonl`
   (fallback: `/home/bull/.claude/projects/-app/{session_id}.jsonl`)
3. Parse JSONL, extract messages:

```python
messages = []
for line in jsonl_file:
    d = json.loads(line)
    if d["type"] == "user":
        msg = d["message"]
        content = extract_text(msg)  # from msg.content[].text
        messages.append({"role": "user", "content": content})
    elif d["type"] == "assistant":
        msg = d["message"]
        thinking = extract_thinking(msg)
        text = extract_text(msg)
        tool_calls = extract_tool_calls(msg)
        if thinking or text or tool_calls:
            messages.append({
                "role": "assistant",
                "thinking": thinking,
                "content": text,
                "tool_calls": tool_calls,
            })
```

4. Return JSON array of messages

### Response Format

Same structure as the current Web Chat SSE events, so the frontend can reuse existing `handleStreamEvent` rendering:

```json
[
  {"role": "user", "content": "幫我查天氣"},
  {"role": "assistant", "thinking": "Let me search...", "content": null, "tool_calls": null},
  {"role": "assistant", "thinking": null, "content": null, "tool_calls": [{"name": "mcp__minimax_search__search", "input": {...}}]},
  {"role": "tool", "content": "Search results..."},
  {"role": "assistant", "thinking": null, "content": "金門今天晴天，28度", "tool_calls": null}
]
```

---

## A3: Chat Page History Display

### Frontend Changes

When selecting a session (any type: web, discord, line, heartbeat):
1. Call `GET /api/chat/{session_id}/history`
2. Populate `messages` array with the response
3. Render using existing message template (user bubble, assistant bubble, thinking collapse, tool call blocks)

This replaces the current behavior where selecting a session shows an empty chat area.

### For Web sessions

After loading history, the chat input remains functional — user can continue the conversation (new messages append to the existing history display + SSE stream as before).

### For Discord/LINE sessions

History is read-only display. Input area remains hidden (these sessions are managed by their respective channels).

---

## A4: Heartbeat Fresh Start

### Change

In `heartbeat.py`, do NOT pass `session_id` to `runner.run()`. Each heartbeat tick starts a fresh Claude Code session.

```python
# Before:
result = await runner.run(prompt, session_id=session_id, ...)

# After:
result = await runner.run(prompt, session_id=None, ...)
```

### Session Tracking

Still save to sessions DB for dashboard visibility (token tracking), but `session_id` gets a new UUID each tick. Old session .jsonl files remain on disk (nightly cleanup can handle them later).

---

## A5: Nightly Compact + Consolidate

### Trigger

New entry in heartbeat scheduler — runs at 03:00 daily (configurable).

### Step 1: Compact eligible sessions

Criteria for compacting a session:
- `token_count > 50,000` AND
- Has new messages since `last_compacted_at` (or `last_compacted_at` is NULL)

For each eligible session:
1. Check if buffer has unprocessed messages for this channel — if so, inject them into a prompt first (so they become part of the session before compacting)
2. `runner.run("/compact", session_id=session_id)`
3. Update `last_compacted_at` in sessions DB
4. Hard delete the buffer entries for this channel (they are now in the compacted session)

### Step 2: Consolidate

One LLM call with all compacted session summaries:

```
你是記憶整理助理。以下是各個對話的最近摘要。
請整理重要資訊，更新 memory/ 目錄下的相關檔案。
你可以自行決定要寫入哪些檔案。

Session 1 (discord:dev-test-channel): ...
Session 2 (line:group:xxx): ...
...
```

Agent uses Read/Write tools to update memory files as it sees fit.

### DB Migration

Sessions table add column:
```sql
ALTER TABLE sessions ADD COLUMN last_compacted_at TEXT;
```

---

## A6: New Settings

Add to `config/settings.json`:

```json
{
  "buffer_time": "10",
  "nightly_compact_hour": "3"
}
```

- `buffer_time`: minutes — messages within this window are injected verbatim; older messages are truncated
- `nightly_compact_hour`: hour (0-23) for nightly compact job

Dashboard Settings page updated to show these fields.

---

## Files to Create/Modify

### New files
| File | Purpose |
|------|---------|
| `src/raisebull/buffer.py` | MessageBuffer class (SQLite CRUD for message_buffer table) |
| `tests/unit/test_buffer.py` | Buffer unit tests |
| `tests/integration/test_history.py` | History API integration tests |

### Modified files
| File | Changes |
|------|---------|
| `src/raisebull/session.py` | Add message_buffer table migration + last_compacted_at column |
| `src/raisebull/discord_bot.py` | Buffer accumulation + three-segment prompt assembly |
| `src/raisebull/webhook_line.py` | Buffer accumulation + @mention detection + three-segment prompt |
| `src/raisebull/main.py` | LINE webhook: buffer non-mention messages instead of ignoring |
| `src/raisebull/heartbeat.py` | Fresh start (no resume) + nightly compact job |
| `src/raisebull/admin/routes_chat.py` | Add history endpoint |
| `src/raisebull/admin/static/pages/chat.js` | Load history on session select |
| `src/raisebull/admin/static/pages/chat.html` | Minor: remove "read-only" hints for non-web sessions |
| `config/settings.json` (workspace.example) | Add buffer_time, nightly_compact_hour |

---

## Tests

| Test file | Count | What |
|-----------|-------|------|
| `tests/unit/test_buffer.py` | ~10 | Buffer CRUD, three-segment prompt assembly, hard delete |
| `tests/integration/test_history.py` | ~5 | History API returns parsed JSONL, handles missing files, empty sessions |
| `tests/unit/test_buffer.py` (LINE) | ~3 | LINE mention detection (is_self, no mention, DM) |
| Existing tests | 0 new | Verify no regressions |

---

## Not in Scope

- Discord threads as sessions (future, depends on this work)
- Buffer persistence across container restarts for Web Chat (Web Chat doesn't buffer — it sends directly)
- Cross-channel session continuation from dashboard
- Upload cleanup based on session compact
