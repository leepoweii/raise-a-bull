# Web Chat File Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add file upload support to Web Chat — users attach files via picker or drag-and-drop, with optional text, processed through the same parser pipeline as Discord/LINE.

**Architecture:** The existing `POST /api/chat/{session_id}/messages` endpoint is extended to accept multipart/form-data (alongside existing JSON). Files are parsed via `process_attachment()`, saved to `workspace/uploads/`, and the filepath+preview is prepended to the prompt. Frontend gets drag-and-drop + file preview bar.

**Tech Stack:** FastAPI (Form + UploadFile), Alpine.js (existing SPA)

**Spec:** `docs/superpowers/specs/2026-04-05-webchat-file-upload-design.md`

---

## File Structure

### Files to modify
| File | Changes |
|------|---------|
| `pyproject.toml` | Add `python-multipart` dependency (required by FastAPI for form/file uploads) |
| `src/raisebull/admin/routes_chat.py` | Split `send_message` into JSON + multipart handler, add file processing |
| `src/raisebull/admin/static/pages/chat.html` | Add drag-and-drop overlay, file preview bar, update input area |
| `src/raisebull/admin/static/pages/chat.js` | Rewrite `send()` to use FormData when files present, add drop handlers, file state |
| `src/raisebull/admin/static/style.css` | Add file preview + drop overlay CSS |
| `tests/integration/test_chat.py` | Add 5 new test cases for file upload |

---

## Task 1: Backend — Multipart File Upload Endpoint

**Files:**
- Modify: `src/raisebull/admin/routes_chat.py`
- Test: `tests/integration/test_chat.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/integration/test_chat.py`:

```python
class TestChatFileUpload:
    @pytest.mark.asyncio
    async def test_send_message_with_file(self, client, mock_runner, tmp_path):
        """Upload a .txt file → file saved to workspace/uploads/ + SSE streams."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            data={"content": ""},
            files={"files": ("test.txt", b"Hello from file", "text/plain")},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # Verify runner was called with attachment prompt
        call_args = mock_runner.run.call_args
        prompt = call_args.kwargs.get("prompt") or call_args[0][0]
        assert "test.txt" in prompt
        assert "Read" in prompt

    @pytest.mark.asyncio
    async def test_send_message_with_file_and_text(self, client, mock_runner):
        """Upload file + text → both appear in prompt."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            data={"content": "請分析這個檔案"},
            files={"files": ("data.csv", b"name,age\nAlice,30", "text/csv")},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        call_args = mock_runner.run.call_args
        prompt = call_args.kwargs.get("prompt") or call_args[0][0]
        assert "data.csv" in prompt
        assert "請分析這個檔案" in prompt

    @pytest.mark.asyncio
    async def test_send_message_file_too_large(self, client):
        """File > 10MB → 413."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        big_content = b"x" * (10 * 1024 * 1024 + 1)
        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            data={"content": ""},
            files={"files": ("big.txt", big_content, "text/plain")},
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_send_message_no_content_no_files(self, client):
        """Empty request (no content, no files) → 400."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            data={"content": ""},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_send_message_json_still_works(self, client, mock_runner):
        """JSON body without files → still works (backward compat)."""
        resp = await client.post("/admin/api/chat/sessions")
        sid = resp.json()["id"]

        resp = await client.post(
            f"/admin/api/chat/{sid}/messages",
            json={"content": "Hello JSON"},
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        events = [json.loads(line[6:]) for line in resp.text.split("\n") if line.startswith("data: ")]
        types = [e["type"] for e in events]
        assert "done" in types
```

- [ ] **Step 1b: Add python-multipart dependency**

Add `"python-multipart>=0.0.9"` to `pyproject.toml` dependencies (required by FastAPI for form/file upload parsing). Then run `uv sync`.

- [ ] **Step 2: Run tests — verify new tests fail**

Run: `cd /Users/pwlee/Documents/Github/raise-a-bull && uv run pytest tests/integration/test_chat.py::TestChatFileUpload -v`
Expected: FAIL (some will 422 because endpoint expects JSON body)

- [ ] **Step 3: Implement multipart support in routes_chat.py**

Replace the `send_message` handler in `src/raisebull/admin/routes_chat.py`. The key change: detect Content-Type to handle both JSON and multipart. Replace everything from line 96 to end of file with:

```python
from fastapi import UploadFile, File, Form
from raisebull.parsers.router import process_attachment
from raisebull.parsers.vision import create_vision_client

_vision_client = create_vision_client()

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/api/chat/{session_id}/messages")
async def send_message(session_id: str, request: Request):
    if session_id not in _web_sessions:
        return JSONResponse({"error": "session not found"}, status_code=404)

    runner = getattr(request.app.state, "runner", None)
    sessions_store = getattr(request.app.state, "sessions", None)

    if runner is None:
        return JSONResponse({"error": "no runner"}, status_code=503)

    # Parse request — JSON or multipart
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        content = form.get("content", "")
        files = form.getlist("files")
        # Filter out empty file entries
        files = [f for f in files if hasattr(f, "filename") and f.filename]
    elif "application/json" in content_type:
        body = await request.json()
        content = body.get("content", "")
        files = []
    else:
        # Try JSON as default
        try:
            body = await request.json()
            content = body.get("content", "")
            files = []
        except Exception:
            return JSONResponse({"error": "unsupported content type"}, status_code=400)

    content = (content or "").strip()
    if not content and not files:
        return JSONResponse({"error": "content or files required"}, status_code=400)

    if len(files) > 5:
        return JSONResponse({"error": "max 5 files per message"}, status_code=400)

    # Process file attachments
    attachment_parts = []
    workspace = getattr(runner, "workspace", "/app/workspace")
    for f in files:
        file_bytes = await f.read()
        if len(file_bytes) > MAX_FILE_SIZE:
            return JSONResponse(
                {"error": f"File too large: {f.filename} ({len(file_bytes)} bytes, max {MAX_FILE_SIZE})"},
                status_code=413,
            )
        try:
            filepath, preview = await process_attachment(
                file_bytes, f.filename, f.content_type or "",
                session_id=session_id, workspace=workspace,
                vision_client=_vision_client,
            )
            attachment_parts.append(
                f"用戶上傳了 {f.filename}，已解析存放在：{filepath}\n"
                f"請用 Read 工具查看完整內容。\n"
                f"前 200 字預覽：\n{preview}"
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Failed to process upload %s", f.filename)
            attachment_parts.append(f"(附件 {f.filename} 處理失敗)")

    # Build final prompt
    prompt_parts = attachment_parts + ([content] if content else [])
    prompt = "\n\n---\n\n".join(prompt_parts)

    claude_session_id = None
    if sessions_store:
        row = await sessions_store.get(session_id)
        if row:
            claude_session_id = row["session_id"]

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_trace(step: TraceStep):
            data = json.dumps(
                {"type": step.step_type, "content": step.content},
                ensure_ascii=False,
            )
            await queue.put(f"data: {data}\n\n")

        async def run_agent():
            try:
                result = await runner.run(
                    prompt,
                    session_id=claude_session_id,
                    on_trace=on_trace,
                    timeout_seconds=300.0,
                )
                if result.stale_session and sessions_store:
                    await sessions_store.clear(session_id)
                    result = await runner.run(
                        prompt,
                        session_id=None,
                        on_trace=on_trace,
                        timeout_seconds=300.0,
                    )
                return result
            except BaseException as e:
                await queue.put(
                    f'data: {json.dumps({"type": "error", "content": str(e)})}\n\n'
                )
                return None
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_agent())

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

        result = await task

        if result and sessions_store:
            existing = await sessions_store.get(session_id)
            existing_tokens = existing["token_count"] if existing else 0
            await sessions_store.save(
                session_id,
                session_id=result.session_id or claude_session_id or "",
                domain="web",
                token_count=existing_tokens + (result.input_tokens or 0) + (result.output_tokens or 0),
            )

        done_data = json.dumps({
            "type": "done",
            "session_id": result.session_id if result else None,
            "tokens": {
                "in": result.input_tokens if result else 0,
                "out": result.output_tokens if result else 0,
            },
            "error": result.error if result else None,
        })
        yield f"data: {done_data}\n\n"

        meta = _web_sessions.get(session_id)
        if meta:
            meta["message_count"] = meta.get("message_count", 0) + 1
            if meta.get("name") is None:
                meta["name"] = (content or "file upload")[:20]

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

Also remove the old `MessageBody` class (line 24-25) and the `from pydantic import BaseModel` import (line 11) since they are no longer used.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/integration/test_chat.py -v`
Expected: all tests PASS (existing + new)

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/unit/ tests/integration/ -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/raisebull/admin/routes_chat.py tests/integration/test_chat.py
git commit -m "feat: Web Chat multipart file upload (JSON + FormData on same endpoint)"
```

---

## Task 2: Frontend — File Picker + Drag-and-Drop + File Preview

**Files:**
- Modify: `src/raisebull/admin/static/pages/chat.html`
- Modify: `src/raisebull/admin/static/pages/chat.js`

- [ ] **Step 1: Update chat.html**

Replace the entire `chat-input-area` section (lines 122-139) with:

```html
                    <!-- File preview bar (shows when files are pending) -->
                    <div class="chat-file-preview" x-show="pendingFiles.length > 0 && currentSessionType !== 'discord'"
                        <template x-for="(f, idx) in pendingFiles" :key="idx">
                            <div class="chat-file-item">
                                <span x-text="'📄 ' + f.name + ' (' + formatFileSize(f.size) + ')'"></span>
                                <button class="chat-file-remove" @click="removePendingFile(idx)">✕</button>
                            </div>
                        </template>
                    </div>

                    <!-- Input area -->
                    <div class="chat-input-area" x-show="currentSessionType !== 'discord'">
                        <label class="chat-upload-btn" title="Upload file">
                            📎
                            <input type="file" multiple style="display:none"
                                   accept=".jpg,.jpeg,.png,.gif,.webp,.pdf,.docx,.xlsx,.pptx,.csv,.md,.txt"
                                   @change="addFiles($event)" x-ref="fileInput">
                        </label>
                        <textarea class="chat-input"
                                  x-model="input"
                                  @keydown.meta.enter="send()"
                                  @keydown.ctrl.enter="send()"
                                  placeholder="Type a message... (Cmd+Enter to send)"
                                  :disabled="sending"
                                  rows="3"></textarea>
                        <button class="btn btn-primary" @click="send()" :disabled="sending || (!input.trim() && pendingFiles.length === 0)">
                            Send
                        </button>
                    </div>
```

Add the drag-and-drop overlay inside the `chat-main` div (after `<!-- Placeholder when no session -->`):

```html
            <!-- Drag and drop overlay -->
            <div class="chat-drop-overlay" x-show="dragActive"
                 @dragover.prevent="dragActive = true"
                 @dragleave.prevent="dragActive = false"
                 @drop.prevent="handleDrop($event)">
                <div class="chat-drop-text">拖放檔案到這裡</div>
            </div>
```

Add dragover/dragleave to the `chat-main` div itself:

Change:
```html
        <div class="card chat-main">
```
To:
```html
        <div class="card chat-main" @dragover.prevent="if(currentSession && currentSessionType !== 'discord') dragActive = true" @dragleave.self="dragActive = false">
```

- [ ] **Step 2: Update chat.js**

Replace the entire `chat.js` content. Key changes:
- Add `pendingFiles: []` and `dragActive: false` to state
- Rewrite `send()` to use FormData when files are pending
- Remove old `uploadFile()`, add `addFiles()`, `removePendingFile()`, `handleDrop()`, `formatFileSize()`
- Client-side validation (10MB per file, max 5 files)

Full replacement for `chat.js`:

```javascript
// Web Chat page Alpine component
window.chatPage = function() {
    return {
        sessions: [],
        currentSession: null,
        currentSessionType: null,
        currentSessionName: null,
        messages: [],
        input: '',
        sending: false,
        pendingFiles: [],
        dragActive: false,

        getApp() {
            const appEl = document.querySelector('[x-data]');
            return Alpine.evaluate(appEl, '$data');
        },

        async load() {
            await this.loadSessions();
        },

        async loadSessions() {
            this.sessions = await this.getApp().api('/api/chat/sessions') || [];
        },

        async newSession() {
            const result = await this.getApp().api('/api/chat/sessions', {
                method: 'POST',
            });
            if (result && result.id) {
                await this.loadSessions();
                await this.selectSession(result.id);
            }
        },

        async selectSession(sid) {
            this.currentSession = sid;
            const session = this.sessions.find(s => s.id === sid);
            this.currentSessionType = session?.type || 'web';
            this.currentSessionName = session?.name || null;
            this.messages = [];
            this.input = '';
            this.pendingFiles = [];
        },

        addFiles(event) {
            const newFiles = Array.from(event.target.files || []);
            this._validateAndAddFiles(newFiles);
            event.target.value = '';
        },

        handleDrop(event) {
            this.dragActive = false;
            const newFiles = Array.from(event.dataTransfer.files || []);
            this._validateAndAddFiles(newFiles);
        },

        _validateAndAddFiles(newFiles) {
            const app = this.getApp();
            for (const f of newFiles) {
                if (f.size > 10 * 1024 * 1024) {
                    app.showToast(`檔案過大：${f.name}（上限 10MB）`, 'error');
                    continue;
                }
                if (this.pendingFiles.length >= 5) {
                    app.showToast('最多 5 個檔案', 'error');
                    break;
                }
                this.pendingFiles.push(f);
            }
        },

        removePendingFile(idx) {
            this.pendingFiles.splice(idx, 1);
        },

        formatFileSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        },

        async send() {
            if (!this.currentSession || this.sending) return;
            const msg = this.input.trim();
            const files = [...this.pendingFiles];
            if (!msg && files.length === 0) return;

            this.input = '';
            this.pendingFiles = [];
            this.sending = true;

            // Optimistic: add user message
            const userContent = files.length > 0
                ? (files.map(f => '📎 ' + f.name).join(', ') + (msg ? '\n' + msg : ''))
                : msg;
            this.messages.push({ role: 'user', content: userContent });
            this.$nextTick(() => this.scrollToBottom());

            try {
                let fetchOpts;
                const url = '/admin/api/chat/' + encodeURIComponent(this.currentSession) + '/messages';

                if (files.length > 0) {
                    const form = new FormData();
                    form.append('content', msg);
                    for (const f of files) form.append('files', f);
                    fetchOpts = {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'Accept': 'text/event-stream' },
                        body: form,
                    };
                } else {
                    fetchOpts = {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'text/event-stream',
                        },
                        body: JSON.stringify({ content: msg }),
                    };
                }

                const resp = await fetch(url, fetchOpts);

                if (resp.status === 401) {
                    window.location.hash = '#/login';
                    return;
                }
                if (resp.status === 413) {
                    this.getApp().showToast('檔案過大（上限 10MB）', 'error');
                    throw new Error('File too large');
                }
                if (!resp.ok) throw new Error('Request failed');

                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        try {
                            const event = JSON.parse(line.slice(6));
                            this.handleStreamEvent(event);
                        } catch (e) { /* skip malformed */ }
                    }
                }

                await this.loadSessions();
            } catch (e) {
                this.input = msg;
                this.pendingFiles = files;
                this.messages.pop();
                this.getApp().showToast('Connection error', 'error');
            }

            this.sending = false;
            this.$nextTick(() => this.scrollToBottom());
        },

        handleStreamEvent(event) {
            if (event.type === 'thinking') {
                this.messages.push({ role: 'assistant', thinking: event.content });
            } else if (event.type === 'tool_call') {
                const c = event.content || {};
                this.messages.push({
                    role: 'assistant',
                    tool_calls: [{ name: c.name, arguments: JSON.stringify(c.input || {}) }],
                });
            } else if (event.type === 'tool_result') {
                this.messages.push({ role: 'tool', content: event.content });
            } else if (event.type === 'text') {
                this.messages.push({ role: 'assistant', content: event.content });
            } else if (event.type === 'error') {
                this.messages.push({ role: 'assistant', content: '⚠️ ' + (event.content || 'Unknown error') });
            } else if (event.type === 'done') {
                // Done — no visual action
            }
            this.$nextTick(() => this.scrollToBottom());
        },

        async deleteSession() {
            if (!this.currentSession) return;
            if (!confirm('Delete this session?')) return;

            const result = await this.getApp().api('/api/chat/' + encodeURIComponent(this.currentSession), {
                method: 'DELETE',
            });

            if (result && result.ok) {
                this.currentSession = null;
                this.currentSessionType = null;
                this.currentSessionName = null;
                this.messages = [];
                this.input = '';
                this.pendingFiles = [];
                await this.loadSessions();
                this.getApp().showToast('Session deleted', 'success');
            }
        },

        scrollToBottom() {
            const el = this.$refs.messageContainer;
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        },

        shortId(sid) {
            if (!sid) return '';
            const parts = sid.split(':');
            return parts[parts.length - 1] || sid;
        },

        renderMarkdown(text) {
            if (!text) return '';
            let s = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
            s = s.replace(/```([\s\S]*?)```/g, '<pre class="chat-code-block">$1</pre>');
            s = s.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>');
            s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            s = s.replace(/\n/g, '<br>');
            return s;
        },
    };
};
export function init(app) { /* Alpine auto-discovers chatPage() via x-data */ }
```

- [ ] **Step 3: Add CSS for file preview and drop overlay**

Append to `src/raisebull/admin/static/style.css` (find the chat section):

```css
/* File upload preview bar */
.chat-file-preview {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 8px 12px;
    border-top: var(--border-width) solid var(--border);
    background: var(--paper);
}
.chat-file-item {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 4px 8px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 12px;
}
.chat-file-remove {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--danger);
    font-size: 14px;
    padding: 0 2px;
}

/* Drag and drop overlay */
.chat-drop-overlay {
    position: absolute;
    inset: 0;
    background: rgba(42, 77, 20, 0.15);
    border: 3px dashed var(--accent);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
    border-radius: 8px;
}
.chat-drop-text {
    font-size: 18px;
    font-weight: 700;
    color: var(--accent);
}
/* NOTE: Add position: relative to the EXISTING .chat-main block in style.css,
   do NOT create a second .chat-main selector. */
```

- [ ] **Step 4: Verify by loading the page**

Start the dev server or check with curl that static files are served correctly:
```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && uv run python -c "
from raisebull.admin import create_admin_app
print('Admin app created OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add src/raisebull/admin/static/pages/chat.html src/raisebull/admin/static/pages/chat.js src/raisebull/admin/static/style.css
git commit -m "feat: Web Chat file upload UI (picker + drag-and-drop + preview bar)"
```

---

## Task 3: Final Verification + Deploy

- [ ] **Step 1: Run all fast tests**

Run: `uv run pytest tests/unit/ tests/integration/ -v`
Expected: all pass (~135 total)

- [ ] **Step 2: Push and rebuild**

```bash
cd /Users/pwlee/Documents/Github/raise-a-bull && git push origin feature/calf-merge
```

Then on samantha-wsl:
```bash
ssh -p 2222 samantha-machine@samantha-wsl.tail5a1118.ts.net
cd ~/raise-a-bull && git pull origin feature/calf-merge
BOT_NAME=daniu BOT_PORT=18888 BOT_ENV_FILE=~/bots/daniu/.env WORKSPACE_PATH=~/bots/daniu/workspace docker compose build
docker stop bull-daniu && docker rm bull-daniu
BOT_NAME=daniu BOT_PORT=18888 BOT_ENV_FILE=~/bots/daniu/.env WORKSPACE_PATH=~/bots/daniu/workspace docker compose up -d
```

- [ ] **Step 3: Verify via dashboard**

```bash
# Login and test file upload via curl (multipart)
ssh samantha-wsl 'curl -s -X POST http://localhost:18888/admin/api/auth -H "Content-Type: application/json" -d "{\"password\":\"daniu2026\"}" -c /tmp/bull-cookie > /dev/null && \
curl -s -b /tmp/bull-cookie -X POST http://localhost:18888/admin/api/chat/sessions | python3 -c "import sys,json; print(json.load(sys.stdin)[\"id\"])"'
# Use the session ID to test multipart upload
```
