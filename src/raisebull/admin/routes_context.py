"""Context file read/write API — workspace/context/*.md."""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/context")


def _context_dir(request: Request) -> Path:
    """Get the workspace context directory."""
    workspace = getattr(request.app.state, "workspace_dir", None)
    if not workspace:
        raise RuntimeError("workspace_dir not configured on app.state")
    return Path(workspace) / "context"


def _validate_filename(filename: str) -> str | None:
    """Validate filename: no path traversal, must be .md. Returns error or None."""
    if "/" in filename or "\\" in filename:
        return "Invalid filename: slashes not allowed"
    if ".." in filename:
        return "Invalid filename: path traversal not allowed"
    if not filename.endswith(".md"):
        return "Invalid filename: only .md files allowed"
    return None


@router.get("")
async def list_context_files(request: Request):
    """List all .md files in workspace/context/ with size and modified time."""
    ctx_dir = _context_dir(request)
    if not ctx_dir.exists():
        return []

    files = []
    for p in sorted(ctx_dir.glob("*.md")):
        stat = p.stat()
        files.append({
            "filename": p.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return files


@router.get("/{filename}")
async def read_context_file(filename: str, request: Request):
    """Read a single context file."""
    error = _validate_filename(filename)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    filepath = _context_dir(request) / filename
    if not filepath.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)

    content = filepath.read_text(encoding="utf-8")
    return {"content": content}


@router.put("/{filename}")
async def write_context_file(filename: str, request: Request):
    """Write a context file atomically (write .tmp then rename)."""
    error = _validate_filename(filename)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    body = await request.json()
    content = body.get("content", "")

    ctx_dir = _context_dir(request)
    ctx_dir.mkdir(parents=True, exist_ok=True)
    filepath = ctx_dir / filename
    tmp_path = ctx_dir / f"{filename}.tmp"

    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.rename(str(tmp_path), str(filepath))
    except Exception as e:
        # Clean up tmp on failure
        if tmp_path.exists():
            tmp_path.unlink()
        return JSONResponse({"error": f"Write failed: {e}"}, status_code=500)

    return {"ok": True}
