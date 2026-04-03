"""Web Chat API — session CRUD + SSE streaming via ClaudeRunner."""

import asyncio
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from raisebull.trace import TraceStep

router = APIRouter()

_web_sessions: dict[str, dict[str, Any]] = {}


def _generate_id() -> str:
    return f"web:{secrets.token_hex(6)}"


class MessageBody(BaseModel):
    content: str


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

    for sid, meta in _web_sessions.items():
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

    if sessions_store:
        try:
            db = sessions_store._require_db()
            async with db.execute(
                "SELECT key, token_count, last_active FROM sessions WHERE key LIKE 'discord:%'"
            ) as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    result.append({
                        "id": row[0],
                        "type": "discord",
                        "name": row[0].split(":")[-1],
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
    if session_id not in _web_sessions:
        return JSONResponse({"error": "session not found"}, status_code=404)

    del _web_sessions[session_id]

    sessions_store = getattr(request.app.state, "sessions", None)
    if sessions_store:
        await sessions_store.clear(session_id)

    return {"ok": True}


@router.post("/api/chat/{session_id}/messages")
async def send_message(session_id: str, body: MessageBody, request: Request):
    if session_id not in _web_sessions:
        return JSONResponse({"error": "session not found"}, status_code=404)

    runner = getattr(request.app.state, "runner", None)
    sessions_store = getattr(request.app.state, "sessions", None)

    if runner is None:
        return JSONResponse({"error": "no runner"}, status_code=503)

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
                    body.content,
                    session_id=claude_session_id,
                    on_trace=on_trace,
                    timeout_seconds=300.0,
                )
                if result.stale_session and sessions_store:
                    await sessions_store.clear(session_id)
                    result = await runner.run(
                        body.content,
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
                meta["name"] = body.content[:20]

    return StreamingResponse(event_stream(), media_type="text/event-stream")
