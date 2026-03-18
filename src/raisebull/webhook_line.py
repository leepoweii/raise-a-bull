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

    # 3. Run Claude
    try:
        result = await runner.run(
            event.message.text,
            session_id=existing_session_id,
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
        session_id=result.session_id or existing_session_id or "",
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
