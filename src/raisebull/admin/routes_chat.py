"""Web Chat API — session CRUD + SSE streaming via ClaudeRunner."""

import asyncio
import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from raisebull.parsers.router import process_attachment
from raisebull.parsers.vision import create_vision_client
from raisebull.trace import TraceStep

logger = logging.getLogger(__name__)

router = APIRouter()

_web_sessions: dict[str, dict[str, Any]] = {}

_vision_client = create_vision_client()
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _generate_id() -> str:
    return f"web:{secrets.token_hex(6)}"


@router.post("/api/chat/sessions")
async def create_session(request: Request):
    sid = _generate_id()
    _web_sessions[sid] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message_count": 0,
        "name": None,
    }
    return {"id": sid}


@router.get("/api/chat/sessions")
async def list_sessions(request: Request):
    sessions_store = getattr(request.app.state, "sessions", None)
    result = []
    seen_keys: set[str] = set()

    # 1. In-memory web sessions (current process only, may have unsaved metadata)
    for sid, meta in _web_sessions.items():
        seen_keys.add(sid)
        token_count = 0
        if sessions_store:
            row = await sessions_store.get(sid)
            if row:
                token_count = row.get("token_count", 0)
        result.append({
            "id": sid,
            "type": "web",
            "name": meta.get("name"),
            "created_at": meta["created_at"],
            "message_count": meta["message_count"],
            "token_count": token_count,
        })

    # 2. All sessions from DB (web sessions survive restart, plus Discord/LINE/Heartbeat)
    if sessions_store:
        try:
            db = sessions_store._require_db()
            async with db.execute(
                "SELECT key, token_count, last_active, domain, name FROM sessions"
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    key = row[0]
                    if key in seen_keys:
                        continue  # already listed from in-memory
                    domain = row[3] if row[3] else "general"
                    db_name = row[4] if len(row) > 4 else None
                    # Determine type from key prefix
                    if key.startswith("web:"):
                        stype = "web"
                    elif key.startswith("discord:"):
                        stype = "discord"
                    elif key.startswith("line:"):
                        stype = "line"
                    elif key.startswith("heartbeat:"):
                        stype = "heartbeat"
                    else:
                        stype = domain
                    display_name = db_name or key.split(":")[-1]
                    result.append({
                        "id": key,
                        "type": stype,
                        "name": display_name,
                        "created_at": row[2],
                        "message_count": 0,
                        "token_count": row[1],
                    })
        except Exception:
            pass

    result.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return result


@router.delete("/api/chat/{session_id}")
async def delete_session(session_id: str, request: Request):
    sessions_store = getattr(request.app.state, "sessions", None)

    # Check if session exists (in-memory or DB)
    in_memory = session_id in _web_sessions
    in_db = False
    if sessions_store:
        row = await sessions_store.get(session_id)
        in_db = row is not None

    if not in_memory and not in_db:
        return JSONResponse({"error": "session not found"}, status_code=404)

    # Remove from in-memory dict
    _web_sessions.pop(session_id, None)

    # Remove from DB + clean uploads
    if sessions_store:
        await sessions_store.clear(session_id)

    # Clean uploads directory
    import os
    import shutil
    workspace = getattr(getattr(request.app.state, "runner", None), "workspace", None)
    if workspace:
        uploads_dir = os.path.join(workspace, "uploads", session_id)
        if os.path.isdir(uploads_dir):
            shutil.rmtree(uploads_dir, ignore_errors=True)

    return {"ok": True}


@router.post("/api/chat/{session_id}/messages")
async def send_message(session_id: str, request: Request):
    sessions_store = getattr(request.app.state, "sessions", None)
    # Allow both in-memory and DB-persisted sessions
    in_memory = session_id in _web_sessions
    in_db = False
    if sessions_store:
        row = await sessions_store.get(session_id)
        in_db = row is not None
    if not in_memory and not in_db:
        return JSONResponse({"error": "session not found"}, status_code=404)
    # Ensure in-memory entry exists for metadata tracking
    if not in_memory:
        _web_sessions[session_id] = {
            "created_at": row["last_active"] if in_db else datetime.now(timezone.utc).isoformat(),
            "message_count": 0,
            "name": row.get("name") if in_db else None,
        }

    runner = getattr(request.app.state, "runner", None)
    if not sessions_store:
        sessions_store = getattr(request.app.state, "sessions", None)

    if runner is None:
        return JSONResponse({"error": "no runner"}, status_code=503)

    # Parse request: multipart/form-data or JSON
    content_type = request.headers.get("content-type", "")
    content = ""
    attachment_parts: list[str] = []

    if "multipart/form-data" in content_type:
        form = await request.form()
        content = (form.get("content") or "").strip()
        file_fields = form.getlist("files")

        # Validate file count
        if len(file_fields) > 5:
            return JSONResponse({"error": "too many files (max 5)"}, status_code=400)

        # Validate each file size
        for upload in file_fields:
            file_bytes = await upload.read()
            if len(file_bytes) > MAX_FILE_SIZE:
                return JSONResponse(
                    {"error": f"file too large: {upload.filename}"},
                    status_code=413,
                )
            filepath, preview = await process_attachment(
                file_bytes=file_bytes,
                filename=upload.filename or "upload",
                content_type=upload.content_type or "",
                session_id=session_id,
                workspace=runner.workspace,
                vision_client=_vision_client,
            )
            attachment_parts.append(
                f"[Attachment: {upload.filename}]\n"
                f"Read the full content from: {filepath}\n"
                f"Preview: {preview}"
            )

        # Require at least one of content or files
        if not content and not attachment_parts:
            return JSONResponse(
                {"error": "content or files required"},
                status_code=400,
            )
    elif "application/x-www-form-urlencoded" in content_type:
        # urlencoded form without files — treat empty content as invalid
        form = await request.form()
        content = (form.get("content") or "").strip()
        if not content:
            return JSONResponse(
                {"error": "content or files required"},
                status_code=400,
            )
    else:
        # JSON body
        try:
            body = await request.json()
            content = body.get("content", "").strip()
        except Exception:
            content = ""

    # Build combined prompt
    parts = attachment_parts[:]
    if content:
        parts.append(content)
    prompt = "\n\n---\n\n".join(parts) if parts else content

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
