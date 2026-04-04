# Phase 3 Sub-phase 2: Web Chat File Upload — Design Spec

**Date:** 2026-04-05
**Status:** Approved
**Depends on:** Sub-phase 1 (parsers + router) ✅ completed

---

## Overview

Add file upload support to the Web Chat dashboard. Users can attach files (+ optional text) via a file picker button or drag-and-drop, then the same parser pipeline from Sub-phase 1 processes the attachment and saves to workspace/uploads/.

---

## API

### Endpoint

`POST /api/chat/{session_id}/messages` — **same endpoint**, extended to accept multipart/form-data.

Currently accepts: `{"content": "..."}` (JSON)

New: also accepts **multipart/form-data** with fields:
- `content`: str (text message, optional)
- `files`: multiple UploadFile (optional, max 5 files, each ≤ 10MB)

Validation: at least one of `content` or `files` must be present.

### Response

Same as current: SSE stream with `thinking`, `text`, `tool_call`, `tool_result`, `done` events.

### Flow

```
User picks files + types text
  → Frontend builds FormData(content, files[])
  → POST multipart/form-data to /api/chat/{session_id}/messages
  → FastAPI receives UploadFile objects
  → For each file:
      bytes = await file.read()
      filepath, preview = await process_attachment(
          bytes, file.filename, file.content_type,
          session_id, workspace, vision_client
      )
      → attachment prompt part built
  → Combined prompt = attachment parts + content text
  → runner.run(prompt, session_id) → SSE stream
```

---

## Backend Changes

### File: `src/raisebull/admin/routes_chat.py`

Current `send_message` handler (line ~96) accepts `MessageBody(content: str)` as JSON body.

Change to: use `Form()` + `UploadFile` parameters instead of Pydantic JSON body. FastAPI can detect multipart/form-data automatically.

```python
@router.post("/{session_id}/messages")
async def send_message(
    session_id: str,
    request: Request,
    content: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
):
```

Process files through `process_attachment()` (same as Discord/LINE handlers), build combined prompt, pass to runner.

### Size limit

Check each file size server-side: `await file.read()` then check `len(bytes) > 10 * 1024 * 1024`. Return 413 if exceeded.

### Vision client

Initialize once at module level (same pattern as discord_bot.py):
```python
from raisebull.parsers.vision import create_vision_client
_vision_client = create_vision_client()
```

---

## Frontend Changes

### File: `src/raisebull/admin/static/pages/chat.html` + `chat.js`

#### File picker button
- 📎 button next to the text input
- Clicking opens a hidden `<input type="file" multiple>` 
- Accepted types: `.txt,.md,.csv,.pdf,.docx,.xlsx,.pptx,.jpg,.jpeg,.png,.gif,.webp`

#### Drag-and-drop
- Drop zone covers the entire chat message area
- On dragover: show semi-transparent overlay with "拖放檔案到這裡" text
- On drop: add files to the pending list
- On dragleave: hide overlay

#### File preview bar
- After selecting files, show a bar above the input area
- Each file: `📄 filename.pdf (1.2 MB) ❌`
- Click ❌ to remove from pending list
- Bar disappears after sending

#### Send logic change
- If files are pending: use `FormData` instead of JSON `fetch`
  ```javascript
  const form = new FormData()
  form.append('content', text)
  for (const f of files) form.append('files', f)
  fetch(url, { method: 'POST', body: form })  // no Content-Type header (browser sets boundary)
  ```
- If no files: keep current JSON `fetch` (backward compatible)

#### Client-side validation
- Single file > 10MB → show error toast, don't send
- Max 5 files per message

---

## Error Handling

| Condition | Where | Behavior |
|-----------|-------|----------|
| File > 10MB | Frontend | Block send, show "檔案過大（上限 10MB）" |
| File > 10MB (bypass) | Backend | Return 413 with error message |
| > 5 files | Frontend | Block send, show "最多 5 個檔案" |
| Unsupported format | Backend | Parser returns "不支援此格式" (existing logic) |
| Parse error | Backend | Log error, include "(附件處理失敗)" in prompt |

---

## Tests

### Integration tests (add to `tests/integration/test_chat.py`)

| Test | What |
|------|------|
| `test_send_message_with_file` | Upload a .txt file → verify file saved to workspace/uploads/ + response streams |
| `test_send_message_with_file_and_text` | Upload file + text → both in prompt |
| `test_send_message_file_too_large` | 11MB file → 413 response |
| `test_send_message_no_content_no_files` | Empty request → 400 |
| `test_send_message_json_still_works` | JSON body without files → still works (backward compat) |

---

## Backward Compatibility

The endpoint must continue to accept JSON `{"content": "..."}` requests from existing clients. FastAPI routes can handle both JSON and multipart on the same endpoint by checking Content-Type, or by having the handler accept both forms.

Approach: Check `Content-Type` header. If `application/json` → parse as JSON (current behavior). If `multipart/form-data` → parse as Form + UploadFile.

---

## Not in Scope

- File type icons in chat history (just show filename text)
- Image preview/thumbnail in chat
- Upload progress bar (just loading state)
- Drag-and-drop reordering of files
