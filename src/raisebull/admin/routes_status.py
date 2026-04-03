"""Status API — live bot/session/heartbeat state."""

import json
from pathlib import Path

from fastapi import APIRouter, Request

from raisebull import heartbeat as _heartbeat_mod

router = APIRouter()


def _read_settings(workspace_dir: str) -> dict:
    path = Path(workspace_dir) / "config" / "settings.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


@router.get("/api/bootstrap")
async def bootstrap(request: Request):
    runner = getattr(request.app.state, "runner", None)
    bot_fn = getattr(request.app.state, "bot_fn", None)
    bot = bot_fn() if bot_fn else None
    bot_connected = bot.is_ready() if bot and hasattr(bot, "is_ready") else False
    sessions = getattr(request.app.state, "sessions", None)

    settings = _read_settings(request.app.state.workspace_dir)

    session_count = 0
    if sessions:
        try:
            db = sessions._require_db()
            async with db.execute("SELECT COUNT(*) FROM sessions") as cursor:
                row = await cursor.fetchone()
                session_count = row[0] if row else 0
        except Exception:
            pass

    return {
        "agent_name": settings.get("agent_name", "Agent"),
        "version": "0.1.0",
        "accent_color": "#2A4D14",
        "sessions_count": session_count,
        "last_heartbeat_time": _heartbeat_mod._last_heartbeat_time,
        "status": "running" if runner else "no runner",
        "bot_connected": bot_connected,
    }


@router.get("/api/status")
async def status(request: Request):
    runner = getattr(request.app.state, "runner", None)
    bot_fn = getattr(request.app.state, "bot_fn", None)
    bot = bot_fn() if bot_fn else None
    bot_connected = bot.is_ready() if bot and hasattr(bot, "is_ready") else False
    sessions = getattr(request.app.state, "sessions", None)

    counts = {"total": 0, "web": 0, "discord": 0, "line": 0, "heartbeat": 0}
    if sessions:
        try:
            db = sessions._require_db()
            async with db.execute("SELECT key FROM sessions") as cursor:
                rows = await cursor.fetchall()
                for row in rows:
                    key = row[0]
                    counts["total"] += 1
                    if key.startswith("web:"):
                        counts["web"] += 1
                    elif key.startswith("discord:"):
                        counts["discord"] += 1
                    elif key.startswith("line:"):
                        counts["line"] += 1
                    elif key.startswith("heartbeat:"):
                        counts["heartbeat"] += 1
        except Exception:
            pass

    return {
        "bot_running": bot_connected,
        "bot_username": bot.user.name if bot and bot.user else None,
        "guilds": len(bot.guilds) if bot and hasattr(bot, "guilds") else 0,
        "sessions": counts,
        "heartbeat_last": _heartbeat_mod._last_heartbeat_time,
        "model": runner.model if runner else None,
        "workspace": runner.workspace if runner else None,
    }
