"""LINE webhook handler for Samantha v2.

Pattern: run Claude, try reply_token first, fall back to push_message if
the token has expired (LINE reply token TTL is ~30 s; Claude may take longer for complex requests).
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiException,
    PushMessageRequest,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    TextMessage,
)

if TYPE_CHECKING:
    from linebot.v3.webhooks import MessageEvent
    from linebot.v3.messaging import MessagingApi

    from raisebull.runner import ClaudeRunner
    from raisebull.session import SessionStore

logger = logging.getLogger(__name__)

from raisebull.discord_bot import _run_with_recovery  # noqa: E402



_LINE_COMMANDS = {"/new", "/info", "/compact"}


async def _handle_line_command(
    text: str,
    user_id: str,
    reply_token: str,
    sessions: "SessionStore",
    runner: "ClaudeRunner",
    messaging_api: "MessagingApi",
) -> bool:
    """Handle /new, /info, /compact from the Rich Menu. Returns True if handled."""
    session_key = f"line:{user_id}"
    cmd = text.strip().lower()

    if cmd == "/new":
        await sessions.clear(session_key)
        _send(user_id, reply_token, "✅ 已開新對話。", messaging_api)
        return True

    if cmd == "/info":
        row = await sessions.get(session_key)
        if row is None:
            _send(user_id, reply_token, "目前沒有進行中的對話。", messaging_api)
        else:
            sid = row["session_id"][:6] if row["session_id"] else "—"
            tokens = row["token_count"]
            last = row["last_active"]
            msg = f"📊 對話狀態\nID: {sid}...\nTokens: {tokens}\n最後活動: {last}"
            _send(user_id, reply_token, msg, messaging_api)
        return True

    if cmd == "/compact":
        row = await sessions.get(session_key)
        existing_session_id = row["session_id"] if row else None
        existing_tokens = row["token_count"] if row else 0
        result = await runner.run("/compact", session_id=existing_session_id)
        if result.error:
            _send(user_id, reply_token, f"⚠️ {result.error}", messaging_api)
        else:
            new_tokens = (result.input_tokens or 0) + (result.output_tokens or 0)
            await sessions.save(
                session_key,
                session_id=result.session_id or existing_session_id or "",
                domain="line",
                token_count=existing_tokens + new_tokens,
            )
            _send(user_id, reply_token, result.text or "✅ 對話已整理。", messaging_api)
        return True

    return False

async def handle_line_message(
    event: "MessageEvent",
    runner: "ClaudeRunner",
    sessions: "SessionStore",
    messaging_api: "MessagingApi",
) -> None:
    """Handle an incoming LINE TextMessage event.

    1. Retrieve existing session (key = line:{user_id}).
    2. Run Claude with the user's prompt.
    3. Try to reply via reply_token; if expired, fall back to push_message.
    4. Save the new session ID to the store.
    """
    user_id: str = event.source.user_id
    session_key = f"line:{user_id}"

    # Handle Rich Menu commands first (fast path, no Claude invocation)
    text = event.message.text.strip()
    if text.lower() in _LINE_COMMANDS:
        await _handle_line_command(text, user_id, event.reply_token, sessions, runner, messaging_api)
        return

    # 1. Get existing session
    row = await sessions.get(session_key)
    existing_session_id = row["session_id"] if row else None
    existing_tokens = row["token_count"] if row else 0

    # 2. Show loading animation (best-effort — non-fatal)
    try:
        messaging_api.show_loading_animation(
            ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=60)
        )
    except Exception:
        logger.warning("show_loading_animation failed (non-fatal)", exc_info=True)

    # 3. Run Claude (with automatic stale-session recovery)
    try:
        result, effective_session_id = await _run_with_recovery(
            runner, sessions, session_key, text, existing_session_id
        )
    except Exception:
        logger.exception("runner.run() raised an exception for user %s", user_id)
        _send(user_id, event.reply_token, "⚠️ 出了點問題，請再試一次。", messaging_api)
        return

    response_text = result.text if result.text else "⚠️ (no response)"

    # 4. Try reply_token first; fall back to push if it has expired
    _send(user_id, event.reply_token, response_text, messaging_api)

    # 5. Save new session (token_count is additive across the session)
    new_tokens = (result.input_tokens or 0) + (result.output_tokens or 0)
    await sessions.save(
        session_key,
        session_id=effective_session_id,
        domain="line",
        token_count=existing_tokens + new_tokens,
    )


def _send(user_id: str, reply_token: str, text: str, messaging_api: "MessagingApi") -> None:
    """Try reply_token; if it has expired, fall back to push_message."""
    try:
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
    except (ApiException, Exception):
        logger.info("reply_token expired or failed, falling back to push_message")
        try:
            messaging_api.push_message(
                PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
            )
        except Exception:
            logger.exception("push_message also failed for user %s", user_id)


def push_to_line(text: str, messaging_api: "MessagingApi") -> None:
    """Push *text* to the LINE user configured in LINE_USER_ID env var.

    Used by the heartbeat scheduler for proactive messages.
    """
    user_id = os.environ["LINE_USER_ID"]
    messaging_api.push_message(
        PushMessageRequest(
            to=user_id,
            messages=[TextMessage(text=text)],
        )
    )
