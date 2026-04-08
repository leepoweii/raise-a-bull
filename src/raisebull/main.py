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
import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, MessagingApiBlob
from linebot.v3.webhooks import MessageEvent, TextMessageContent, ImageMessageContent, FileMessageContent

import discord

from raisebull.buffer import MessageBuffer
from raisebull.runner import ClaudeRunner
from raisebull.session import SessionStore
from raisebull.discord_bot import run_discord_bot, get_bot
from raisebull.heartbeat import start_heartbeat, run_event_check, nightly_compact
from raisebull.webhook_line import handle_line_message, handle_line_attachment
from raisebull.admin import create_admin_app

load_dotenv()

# Configure application logging at module load so logger.info() calls from
# raisebull.heartbeat, raisebull.discord_bot, raisebull.session, etc. surface
# in uvicorn stdout / docker logs. Without this, Python's root logger defaults
# to WARNING and uvicorn only configures its own loggers (uvicorn,
# uvicorn.access, uvicorn.error) — application INFO lines like "Nightly
# compact: no eligible sessions (threshold=50000)" are silently dropped,
# leaving operators blind to scheduled job behavior.
#
# Configurable via LOG_LEVEL env var (default INFO). Deployments that want
# to suppress chatty INFO output can set LOG_LEVEL=WARNING in their .env —
# useful for privacy-sensitive cases since some INFO lines include session
# keys (e.g., "discord:1490304831116673064") and first-50-chars of heartbeat
# outputs (in the channel push path at heartbeat.py:117). Default INFO is
# the right call for samantha-wsl ops where the operator owns all the data,
# but the override exists for hosted/multi-tenant scenarios.
#
# Two-step setup for robustness:
#   1. basicConfig — adds a StreamHandler to the root logger if root has no
#      handlers (the production uvicorn case). Idempotent: no-op when root
#      already has handlers (the pytest-with-log-capture case). Provides the
#      DEFAULT FORMAT used in production stdout.
#   2. setLevel on the raisebull logger — explicitly enables emission at the
#      configured level for all raisebull.* descendants regardless of what
#      configured root. Deterministic: works even if step 1 was a no-op
#      (e.g., pytest already added root handlers at a higher level).
#
# uvicorn's own loggers set propagate=False so we don't get double-logging
# on uvicorn lines.
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_RAW_LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
if _RAW_LOG_LEVEL in _VALID_LOG_LEVELS:
    _LOG_LEVEL = _RAW_LOG_LEVEL
    _log_level_fallback_msg: str | None = None
else:
    # A typo in .env (e.g. LOG_LEVEL=WARNNG) would otherwise raise ValueError
    # in basicConfig/setLevel at module import → bot can't boot. Fall back to
    # INFO and emit a warning AFTER the logger is configured, so operators
    # can spot the bad value in stdout / docker logs without losing the bot.
    _LOG_LEVEL = "INFO"
    _log_level_fallback_msg = (
        f"LOG_LEVEL={_RAW_LOG_LEVEL!r} is not a valid Python logging level "
        f"(expected one of {sorted(_VALID_LOG_LEVELS)}); defaulting to INFO"
    )

logging.basicConfig(
    level=_LOG_LEVEL,
    format="%(levelname)-8s %(name)s: %(message)s",
)
logging.getLogger("raisebull").setLevel(_LOG_LEVEL)

logger = logging.getLogger(__name__)
if _log_level_fallback_msg:
    logger.warning(_log_level_fallback_msg)

# ---------------------------------------------------------------------------
# Global singletons (populated in lifespan)
# ---------------------------------------------------------------------------

_sessions: SessionStore | None = None
_runner: ClaudeRunner | None = None
_message_buffer: MessageBuffer | None = None
_heartbeat_push = None  # set in lifespan


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _sessions, _runner, _message_buffer, _heartbeat_push

    if not os.getenv("LINE_CHANNEL_SECRET"):
        raise RuntimeError("LINE_CHANNEL_SECRET must be set")
    if not os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN must be set")

    _sessions = SessionStore(db_path=os.getenv("DB_PATH", "/app/data/sessions.db"))
    await _sessions.init()

    _message_buffer = MessageBuffer(db_path=os.getenv("DB_PATH", "/app/data/sessions.db"))
    await _message_buffer.init()

    _runner = ClaudeRunner(
        claude_bin=os.getenv("CLAUDE_BIN", "claude"),
        workspace=os.getenv("WORKSPACE", "/app/workspace"),
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
    )

    # Inject runner + sessions into admin app (created at module level, populated here)
    _admin_app.state.runner = _runner
    _admin_app.state.sessions = _sessions

    # Wire heartbeat → Discord push via the bot's channel cache
    async def heartbeat_push(channel_name: str, message: str) -> None:
        bot_instance = get_bot()
        if bot_instance is None:
            logger.warning("Heartbeat push: bot not running, skipping #%s", channel_name)
            return
        guild = bot_instance.guilds[0] if bot_instance.guilds else None
        if guild is None:
            return
        channel = discord.utils.get(guild.text_channels, name=channel_name)
        if channel:
            await channel.send(message[:2000])
        else:
            logger.warning("Heartbeat push: #%s not found", channel_name)

    _heartbeat_push = heartbeat_push
    start_heartbeat(_runner, _sessions, push_fn=_heartbeat_push, buffer=_message_buffer)

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
    if _message_buffer is not None:
        await _message_buffer.close()
    logger.info("raise-a-bull shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="raise-a-bull", version="0.1.0", lifespan=lifespan)

# Mount admin dashboard at module level (route table frozen before lifespan)
_data_dir = os.getenv("DATA_DIR") or os.getenv("WORKSPACE", "/app/workspace")
_admin_app = create_admin_app(
    db_path=os.getenv("CREDENTIALS_DB_PATH", os.path.join(_data_dir, "credentials.db")),
    workspace_dir=os.getenv("WORKSPACE", "/app/workspace"),
    bot_fn=get_bot,
)
app.mount("/admin", _admin_app)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


# ---------------------------------------------------------------------------
# Internal API — localhost-only endpoints
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel


class DiscordPushRequest(_BaseModel):
    channel_id: str
    message: str


def _require_localhost(request: Request) -> None:
    """Reject non-localhost callers with 403.

    Used by /internal/* endpoints that should only be invoked by:
      - The same Python process (e.g., heartbeat scheduler firing a task)
      - A shell inside the same container (`docker exec ... curl 127.0.0.1:8000/...`)
      - Test code via ASGITransport (client defaults to ("127.0.0.1", 123) in
        httpx 0.28+ so the loopback check accepts it)

    Tailnet IPs, the Docker bridge gateway IP, and any forwarded request from
    the published port are all rejected on purpose. If a future feature needs to
    expose nightly_compact via a dashboard "Run now" button, it must NOT bypass
    this gate by adding more allowed IPs — instead, add a NEW dashboard route
    (e.g., POST /admin/api/nightly-compact/run) that goes through the existing
    cookie-based auth_middleware and then calls nightly_compact() directly.
    The /internal/* path is reserved for in-process / in-container callers.

    Loopback recognition uses ipaddress.ip_address().is_loopback which on
    Python 3.12+ correctly handles 127.0.0.1, ::1, AND IPv4-mapped IPv6 like
    ::ffff:127.0.0.1 (which some Linux dual-stack uvicorn configs serve as
    the loopback address).
    """
    client = request.client
    if client is None:
        return
    try:
        if ipaddress.ip_address(client.host).is_loopback:
            return
    except ValueError:
        pass  # not a parseable IP — fall through to 403
    raise HTTPException(status_code=403, detail="localhost only")


@app.post("/internal/discord/push")
async def discord_push(req: DiscordPushRequest, request: Request) -> dict[str, Any]:
    """Push a message to a Discord channel via the running bot. Localhost only."""
    _require_localhost(request)
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
            blob_api = MessagingApiBlob(api_client)
            for event in events:
                if not isinstance(event, MessageEvent):
                    continue
                if isinstance(event.message, TextMessageContent):
                    await handle_line_message(
                        event, _runner, _sessions, messaging_api,
                        buffer=_message_buffer,
                    )
                elif isinstance(event.message, (ImageMessageContent, FileMessageContent)):
                    await handle_line_attachment(
                        event, _runner, _sessions, messaging_api, blob_api
                    )

    asyncio.create_task(_process())
    return Response(content="OK", status_code=200)


@app.post("/internal/heartbeat/trigger")
async def heartbeat_trigger(request: Request) -> dict[str, Any]:
    """Manually trigger one heartbeat tick (for testing). Localhost only."""
    _require_localhost(request)
    asyncio.create_task(run_event_check(_runner, _sessions, push_fn=_heartbeat_push))
    return {"ok": True, "message": "heartbeat tick started"}


@app.post("/internal/nightly-compact/trigger")
async def nightly_compact_trigger(request: Request) -> dict[str, Any]:
    """Manually trigger nightly compact (for testing). Localhost only."""
    _require_localhost(request)
    asyncio.create_task(nightly_compact(_runner, _sessions, buffer=_message_buffer))
    return {"ok": True, "message": "nightly compact started"}
