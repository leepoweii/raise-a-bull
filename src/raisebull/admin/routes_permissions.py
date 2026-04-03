"""Permissions API — Discord role mapping + channel config via JSON."""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/permissions")

_DEFAULTS = {
    "role_mappings": [
        {"discord_role": "Admin", "erp_role": "admin"},
        {"discord_role": "Manager", "erp_role": "manager"},
        {"discord_role": "Staff", "erp_role": "staff"},
    ],
    "channel_config": [
        {"channel_name": "management", "role_ceiling": "admin"},
        {"channel_name": "daily-ops", "role_ceiling": "manager"},
        {"channel_name": "shipping", "role_ceiling": "staff"},
    ],
}


def _permissions_path(request: Request) -> Path:
    workspace = request.app.state.workspace_dir
    return Path(workspace) / "config" / "permissions.json"


def _read_permissions(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULTS)


@router.get("")
async def get_permissions(request: Request):
    return _read_permissions(_permissions_path(request))


@router.put("")
async def put_permissions(request: Request):
    body = await request.json()
    data = {
        "role_mappings": body.get("role_mappings", []),
        "channel_config": body.get("channel_config", []),
    }
    path = _permissions_path(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(str(tmp), str(path))
    return {"ok": True}


@router.get("/discord-roles")
async def get_discord_roles(request: Request):
    bot_fn = request.app.state.bot_fn
    bot = bot_fn() if bot_fn else None
    if not bot or not bot.is_ready() or not bot.guilds:
        return {"roles": [], "available": False}
    guild = bot.guilds[0]
    roles = [
        {"name": role.name, "id": str(role.id), "color": str(role.color)}
        for role in guild.roles if not role.is_default()
    ]
    return {"roles": roles, "available": True}


@router.get("/discord-channels")
async def get_discord_channels(request: Request):
    bot_fn = request.app.state.bot_fn
    bot = bot_fn() if bot_fn else None
    if not bot or not bot.is_ready() or not bot.guilds:
        return {"channels": [], "available": False}
    guild = bot.guilds[0]
    channels = [{"name": ch.name, "id": str(ch.id)} for ch in guild.text_channels]
    return {"channels": channels, "available": True}
