"""FastAPI application entry point for raise-a-bull.

Lifespan:
  - startup: init session store, start heartbeat and Discord bot
  - shutdown: close session store

Routes:
  - GET  /health            → {"status": "ok", "version": "0.1.0"}
  - POST /webhook/line      → LINE webhook (signature-verified)
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from raisebull.runner import ClaudeRunner
from raisebull.session import SessionStore
from raisebull.discord_bot import run_discord_bot, get_bot
from raisebull.heartbeat import start_heartbeat, run_event_check
from raisebull.webhook_line import handle_line_message

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global singletons (populated in lifespan)
# ---------------------------------------------------------------------------

_sessions: SessionStore | None = None
_runner: ClaudeRunner | None = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sessions, _runner

    if not os.getenv("LINE_CHANNEL_SECRET"):
        raise RuntimeError("LINE_CHANNEL_SECRET must be set")
    if not os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN must be set")

    _sessions = SessionStore(db_path=os.getenv("DB_PATH", "/app/data/sessions.db"))
    await _sessions.init()

    _runner = ClaudeRunner(
        claude_bin=os.getenv("CLAUDE_BIN", "claude"),
        workspace=os.getenv("WORKSPACE", "/app/workspace"),
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
    )

    start_heartbeat(_runner, _sessions)

    if os.getenv("DISCORD_BOT_TOKEN"):
        async def _discord_task() -> None:
            try:
                await run_discord_bot(_runner, _sessions)
            except Exception:
                logger.exception("Discord bot crashed")
        asyncio.create_task(_discord_task())
    else:
        logger.warning("DISCORD_BOT_TOKEN not set - Discord bot will not start")

    logger.info("raise-a-bull startup complete")

    yield

    if _sessions is not None:
        await _sessions.close()
    logger.info("raise-a-bull shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="raise-a-bull", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# Internal API — Discord push (localhost only; called by heartbeat/scripts)
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel


class DiscordPushRequest(_BaseModel):
    channel_id: str
    message: str


@app.post("/internal/discord/push")
async def discord_push(req: DiscordPushRequest) -> dict[str, Any]:
    """Push a message to a Discord channel via the running bot."""
    bot = get_bot()
    if bot is None:
        raise HTTPException(status_code=503, detail="Discord bot not running")
    channel = bot.get_channel(int(req.channel_id))
    if channel is None:
        raise HTTPException(status_code=404, detail=f"Channel {req.channel_id} not in cache")
    await channel.send(req.message)
    return {"ok": True, "channel_id": req.channel_id}


@app.post("/webhook/line")
async def webhook_line(request: Request) -> Response:
    """Receive LINE webhook events."""
    channel_secret = os.getenv("LINE_CHANNEL_SECRET", "")
    access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

    body = await request.body()
    body_text = body.decode("utf-8")

    signature = request.headers.get("X-Line-Signature", "")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature header")

    parser = WebhookParser(channel_secret)
    try:
        events = parser.parse(body_text, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    async def _process() -> None:
        configuration = Configuration(access_token=access_token)
        with ApiClient(configuration) as api_client:
            messaging_api = MessagingApi(api_client)
            for event in events:
                if isinstance(event, MessageEvent) and isinstance(
                    event.message, TextMessageContent
                ):
                    await handle_line_message(
                        event, _runner, _sessions, messaging_api
                    )

    asyncio.create_task(_process())
    return Response(content="OK", status_code=200)


@app.post("/internal/heartbeat/trigger")
async def heartbeat_trigger() -> dict[str, Any]:
    """Manually trigger one heartbeat tick (for testing). Localhost only."""
    asyncio.create_task(run_event_check(_runner, _sessions))
    return {"ok": True, "message": "heartbeat tick started"}
