"""Heartbeat task list API — parse/write heartbeat.md + last-run.json."""

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/heartbeat")

# Pattern: - [task-id] description
_TASK_RE = re.compile(r"^-\s+\[([^\]]+)\]\s+(.+)$")
# Pattern: <!-- - [task-id] description -->
_DISABLED_RE = re.compile(r"^<!--\s*-\s+\[([^\]]+)\]\s+(.+?)\s*-->$")
# Pattern: ## schedule header
_SCHEDULE_RE = re.compile(r"^##\s+(.+)$")


def _heartbeat_dir(request: Request) -> Path:
    workspace = getattr(request.app.state, "workspace_dir", None)
    if not workspace:
        raise RuntimeError("workspace_dir not configured on app.state")
    return Path(workspace) / "heartbeat"


def _parse_heartbeat(text: str) -> list[dict]:
    """Parse heartbeat.md into a list of task dicts.

    Returns empty list if no valid tasks found (graceful on malformed input).
    """
    tasks = []
    current_schedule = ""
    in_code_block = False

    for line in text.splitlines():
        stripped = line.strip()

        # Skip fenced code blocks (``` ... ```)
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        line = stripped

        # Check schedule header
        m = _SCHEDULE_RE.match(line)
        if m:
            current_schedule = m.group(1).strip()
            continue

        # Check disabled task
        m = _DISABLED_RE.match(line)
        if m:
            tasks.append({
                "task_id": m.group(1),
                "description": m.group(2).strip(),
                "schedule": current_schedule,
                "enabled": False,
            })
            continue

        # Check enabled task
        m = _TASK_RE.match(line)
        if m:
            tasks.append({
                "task_id": m.group(1),
                "description": m.group(2).strip(),
                "schedule": current_schedule,
                "enabled": True,
            })

    return tasks


def _read_last_run(heartbeat_dir: Path) -> dict:
    """Read last-run.json. Returns empty dict on missing/malformed."""
    lr_path = heartbeat_dir / "last-run.json"
    if not lr_path.exists():
        return {}
    try:
        return json.loads(lr_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@router.get("")
async def get_heartbeat(request: Request):
    """Get heartbeat tasks, last run times, and raw markdown."""
    hb_dir = _heartbeat_dir(request)
    hb_path = hb_dir / "heartbeat.md"

    if not hb_path.exists():
        return {"tasks": [], "last_run": {}, "raw_markdown": ""}

    raw = hb_path.read_text(encoding="utf-8")
    tasks = _parse_heartbeat(raw)
    last_run = _read_last_run(hb_dir)

    return {
        "tasks": tasks,
        "last_run": last_run,
        "raw_markdown": raw,
    }


@router.put("")
async def put_heartbeat(request: Request):
    """Write heartbeat.md atomically."""
    body = await request.json()
    content = body.get("content", "")

    hb_dir = _heartbeat_dir(request)
    hb_dir.mkdir(parents=True, exist_ok=True)
    hb_path = hb_dir / "heartbeat.md"
    tmp_path = hb_dir / "heartbeat.md.tmp"

    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.rename(str(tmp_path), str(hb_path))
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        return JSONResponse({"error": f"Write failed: {e}"}, status_code=500)

    return {"ok": True}
