"""Admin Dashboard — FastAPI sub-application."""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from raisebull.admin.auth import auth_middleware, login_endpoint
from raisebull.admin.credentials_db import init_credentials_db


def create_admin_app(
    db_path: str | None = None,
    workspace_dir: str | None = None,
    bot_fn=None,
    runner=None,
    sessions=None,
) -> FastAPI:
    app = FastAPI(title="raise-a-bull Admin")

    data_dir = os.getenv("DATA_DIR", "/app/data")
    app.state.db_path = db_path or os.path.join(data_dir, "credentials.db")
    app.state.workspace_dir = workspace_dir or os.getenv("WORKSPACE", "/app/workspace")
    app.state.bot_fn = bot_fn
    app.state.runner = runner
    app.state.sessions = sessions

    init_credentials_db(app.state.db_path)

    app.middleware("http")(auth_middleware)
    app.post("/api/auth")(login_endpoint)

    from raisebull.admin.routes_status import router as status_router
    from raisebull.admin.routes_context import router as context_router
    from raisebull.admin.routes_skills import router as skills_router
    from raisebull.admin.routes_heartbeat import router as heartbeat_router
    from raisebull.admin.routes_credentials import router as credentials_router
    from raisebull.admin.routes_settings import router as settings_router
    from raisebull.admin.routes_permissions import router as permissions_router
    from raisebull.admin.routes_models import router as models_router
    from raisebull.admin.routes_chat import router as chat_router

    app.include_router(status_router)
    app.include_router(context_router)
    app.include_router(skills_router)
    app.include_router(heartbeat_router)
    app.include_router(credentials_router)
    app.include_router(settings_router)
    app.include_router(permissions_router)
    app.include_router(models_router)
    app.include_router(chat_router)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="admin-static")

    return app
