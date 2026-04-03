"""Models API — list available LLM models with JSON override."""

import json
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/models")

_FALLBACK_MODELS = [
    {"id": "MiniMax-M2.7", "name": "MiniMax M2.7 (Recursive Self-Improvement, ~60 tps)"},
    {"id": "MiniMax-M2.7-highspeed", "name": "MiniMax M2.7 Highspeed (~100 tps)"},
    {"id": "MiniMax-M2.5", "name": "MiniMax M2.5 (Peak Performance, ~60 tps)"},
    {"id": "MiniMax-M2.5-highspeed", "name": "MiniMax M2.5 Highspeed (~100 tps)"},
    {"id": "MiniMax-M2.1", "name": "MiniMax M2.1 (Multi-Language, ~60 tps)"},
    {"id": "MiniMax-M2.1-highspeed", "name": "MiniMax M2.1 Highspeed (~100 tps)"},
    {"id": "MiniMax-M2", "name": "MiniMax M2 (Agentic, Advanced Reasoning)"},
]


@router.get("")
async def list_models(request: Request):
    workspace = request.app.state.workspace_dir
    models_path = Path(workspace) / "config" / "models.json"
    if models_path.exists():
        try:
            return json.loads(models_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return _FALLBACK_MODELS
