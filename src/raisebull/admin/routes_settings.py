"""Settings API — read/write workspace/config/settings.json.

Merge priority: default → env var → JSON file.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/settings")

_ALLOWED_KEYS: dict[str, tuple[str, str | None]] = {
    "agent_name": ("Agent", "AGENT_NAME"),
    "model": ("MiniMax-M2.7", "AGENT_MODEL"),
    "max_steps": ("100", "AGENT_MAX_STEPS"),
    "auto_reply_timeout": ("180", "AUTO_REPLY_TIMEOUT"),
    "session_idle_timeout": ("1800", "SESSION_IDLE_TIMEOUT"),
    "heartbeat_interval": ("1800", "HEARTBEAT_INTERVAL"),
}


def _settings_path(request: Request) -> Path:
    workspace = request.app.state.workspace_dir
    return Path(workspace) / "config" / "settings.json"


def _read_settings(path: Path) -> dict:
    settings = {}
    for key, (default_val, env_name) in _ALLOWED_KEYS.items():
        value = default_val
        if env_name:
            env_val = os.getenv(env_name, "").strip()
            if env_val:
                value = env_val
        settings[key] = value
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            for key in _ALLOWED_KEYS:
                if key in stored:
                    settings[key] = stored[key]
        except (json.JSONDecodeError, OSError):
            pass
    return settings


@router.get("")
async def get_settings(request: Request):
    return _read_settings(_settings_path(request))


@router.put("")
async def put_settings(request: Request):
    body = await request.json()
    path = _settings_path(request)
    current = _read_settings(path)
    for key in _ALLOWED_KEYS:
        if key in body:
            current[key] = str(body[key])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return {"ok": True}
