"""Skills editor API — workspace/skills/*/SKILL.md.

Each skill is a directory containing SKILL.md (and optionally other files).
API returns folder structure (files array) for future full management.
MVP only reads/writes SKILL.md.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/skills")


def _skills_dir(request: Request) -> Path:
    """Get the workspace skills directory."""
    workspace = getattr(request.app.state, "workspace_dir", None)
    if not workspace:
        raise RuntimeError("workspace_dir not configured on app.state")
    return Path(workspace) / "skills"


def _validate_skill_name(name: str) -> str | None:
    """Validate skill name: no path traversal. Returns error or None."""
    if "/" in name or "\\" in name:
        return "Invalid skill name: slashes not allowed"
    if ".." in name:
        return "Invalid skill name: path traversal not allowed"
    return None


def _list_files(skill_path: Path) -> list[str]:
    """List all files in a skill directory (non-recursive, files only)."""
    if not skill_path.is_dir():
        return []
    return sorted(f.name for f in skill_path.iterdir() if f.is_file())


@router.get("")
async def list_skills(request: Request):
    """List all skill directories with their files."""
    skills = _skills_dir(request)
    if not skills.exists():
        return []

    result = []
    for d in sorted(skills.iterdir()):
        if not d.is_dir():
            continue
        skill_md = d / "SKILL.md"
        stat = skill_md.stat() if skill_md.exists() else None
        result.append({
            "name": d.name,
            "files": _list_files(d),
            "size": stat.st_size if stat else 0,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat() if stat else None,
        })
    return result


@router.get("/{skill_name}")
async def read_skill(skill_name: str, request: Request):
    """Read a skill's SKILL.md content."""
    error = _validate_skill_name(skill_name)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    skill_path = _skills_dir(request) / skill_name
    if not skill_path.is_dir():
        return JSONResponse({"error": "Skill not found"}, status_code=404)

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return JSONResponse({"error": "SKILL.md not found in skill directory"}, status_code=404)

    content = skill_md.read_text(encoding="utf-8")
    return {
        "name": skill_name,
        "content": content,
        "files": _list_files(skill_path),
    }


@router.put("/{skill_name}")
async def write_skill(skill_name: str, request: Request):
    """Write a skill's SKILL.md atomically."""
    error = _validate_skill_name(skill_name)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    skill_path = _skills_dir(request) / skill_name
    if not skill_path.is_dir():
        return JSONResponse({"error": "Skill not found"}, status_code=404)

    body = await request.json()
    content = body.get("content", "")

    skill_md = skill_path / "SKILL.md"
    tmp_path = skill_path / "SKILL.md.tmp"

    try:
        tmp_path.write_text(content, encoding="utf-8")
        os.rename(str(tmp_path), str(skill_md))
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink()
        return JSONResponse({"error": f"Write failed: {e}"}, status_code=500)

    return {"ok": True}
