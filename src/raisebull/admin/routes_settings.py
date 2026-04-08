"""Settings API — read/write workspace/config/settings.json.

Merge priority: default → env var → JSON file.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/settings")

_ALLOWED_KEYS: dict[str, tuple[str, str | None]] = {
    "agent_name": ("Agent", "AGENT_NAME"),
    "model": ("MiniMax-M2.7", "AGENT_MODEL"),
    "max_steps": ("100", "AGENT_MAX_STEPS"),
    "auto_reply_timeout": ("180", "AUTO_REPLY_TIMEOUT"),
    "session_idle_timeout": ("1800", "SESSION_IDLE_TIMEOUT"),
    "heartbeat_interval": ("1800", "HEARTBEAT_INTERVAL"),
    "buffer_time": ("10", "BUFFER_TIME"),
    "nightly_compact_hour": ("3", "NIGHTLY_COMPACT_HOUR"),
    "nightly_compact_threshold": ("50000", "NIGHTLY_COMPACT_THRESHOLD"),
    "line_trigger_prefix": ("小牛兒", "LINE_TRIGGER_PREFIX"),
}

# Per-key constraints for numeric settings. Validated on PUT to prevent
# garbage values being displayed by GET while their runtime consumers
# silently fall back to defaults (the dashboard ↔ runtime divergence class
# of bug). Each entry is (min_value, max_value or None for unbounded,
# description for the canonical "{key} must be {description}" error).
#
# heartbeat_interval and buffer_time accept 0:
#  - heartbeat_interval=0 disables the heartbeat scheduler (heartbeat.py:256)
#  - buffer_time=0 collapses the recent-window in MessageBuffer.build_prompt
#
# Keys NOT in this dict (agent_name, model, line_trigger_prefix) are
# string settings and accept any value.
_NUMERIC_CONSTRAINTS: dict[str, tuple[int, int | None, str]] = {
    "max_steps": (1, None, "a positive integer"),
    "auto_reply_timeout": (1, None, "a positive integer (seconds)"),
    "session_idle_timeout": (1, None, "a positive integer (seconds)"),
    "heartbeat_interval": (0, None, "a non-negative integer (0 disables heartbeat)"),
    "buffer_time": (0, None, "a non-negative integer (minutes)"),
    "nightly_compact_hour": (0, 23, "an integer between 0 and 23"),
    "nightly_compact_threshold": (1, None, "a positive integer"),
}


def _validate_numeric_setting(key: str, raw_value) -> str | None:
    """Return canonical error message if invalid, None if valid.

    Validation steps:
      1. Coerce to int via `int(str(raw_value).strip())`. Catches `ValueError`
         (non-numeric, empty, whitespace-only, float-like "3.7", "1e5"),
         `TypeError`, and `AttributeError` (None, dict, etc).
      2. Enforce min_value <= n (always).
      3. Enforce n <= max_value if max_value is not None.

    The error message is `f"{key} must be {description}"` for a single
    canonical format clients can match on by key.
    """
    if key not in _NUMERIC_CONSTRAINTS:
        return None
    min_val, max_val, description = _NUMERIC_CONSTRAINTS[key]
    canonical = f"{key} must be {description}"
    try:
        n = int(str(raw_value).strip())
    except (ValueError, TypeError, AttributeError):
        return canonical
    if n < min_val:
        return canonical
    if max_val is not None and n > max_val:
        return canonical
    return None


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

    # Validate every numeric setting present in the body. The first invalid key
    # wins (deterministic order via _NUMERIC_CONSTRAINTS dict iteration).
    for key in _NUMERIC_CONSTRAINTS:
        if key in body:
            err = _validate_numeric_setting(key, body[key])
            if err:
                return JSONResponse({"error": err}, status_code=400)

    audit_log = getattr(request.app.state, "audit_log", None)
    source_ip = request.client.host if request.client else None

    path = _settings_path(request)
    current = _read_settings(path)
    changes: list[tuple[str, str, str]] = []  # (key, before, after)
    for key in _ALLOWED_KEYS:
        if key in body:
            new_val = str(body[key])
            old_val = current[key]
            if new_val != old_val:
                changes.append((key, old_val, new_val))
            current[key] = new_val

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))

    if audit_log is not None and changes:
        for key, before, after in changes:
            await audit_log.record(
                "settings.put",
                actor="admin",
                target=key,
                before_val=before,
                after_val=after,
                source_ip=source_ip,
            )
    return {"ok": True}
