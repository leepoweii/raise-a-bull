"""LINE webhook handler for raise-a-bull.

Pattern: run Claude, try reply_token first, fall back to push_message if
the token has expired (LINE reply token TTL is ~30 s; Claude may take longer for complex requests).

Session scoping:
  - Group chat  → session_key = line:group:{group_id}, prompt prefixed with speaker user_id
  - DM (1:1)    → session_key = line:{user_id}, prompt sent as-is
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


# ---------------------------------------------------------------------------
# Context resolution
# ---------------------------------------------------------------------------

def _resolve_context(event: "MessageEvent") -> tuple[str, str, str]:
    """Return (session_key, prompt, chat_id) based on source type.

    - Group: session shared by group, prompt prefixed with speaker identity,
             chat_id = group_id (so push fallback goes to the group).
    - DM:    session per user, prompt as-is, chat_id = user_id.
    """
    source = event.source
    user_id: str = source.user_id
    text: str = event.message.text.strip()

    if source.type == "group":
        return (
            f"line:group:{source.group_id}",
            f"[用戶 {user_id}]: {text}",
            source.group_id,
        )
    else:
        return (
            f"line:{user_id}",
            text,
            user_id,
        )


# ---------------------------------------------------------------------------
# Rich Menu command handler
# ---------------------------------------------------------------------------

async def _handle_line_command(
    text: str,
    session_key: str,
    reply_token: str,
    chat_id: str,
    sessions: "SessionStore",
    runner: "ClaudeRunner",
    messaging_api: "MessagingApi",
) -> bool:
    """Handle /new, /info, /compact from the Rich Menu. Returns True if handled."""
    cmd = text.strip().lower()

    if cmd == "/new":
        await sessions.clear(session_key)
        _send(chat_id, reply_token, "✅ 已開新對話。", messaging_api)
        return True

    if cmd == "/info":
        row = await sessions.get(session_key)
        if row is None:
            _send(chat_id, reply_token, "目前沒有進行中的對話。", messaging_api)
        else:
            sid = row["session_id"][:6] if row["session_id"] else "—"
            tokens = row["token_count"]
            last = row["last_active"]
            msg = f"📊 對話狀態\nID: {sid}...\nTokens: {tokens}\n最後活動: {last}"
            _send(chat_id, reply_token, msg, messaging_api)
        return True

    if cmd == "/compact":
        row = await sessions.get(session_key)
        existing_session_id = row["session_id"] if row else None
        existing_tokens = row["token_count"] if row else 0
        result = await runner.run("/compact", session_id=existing_session_id)
        if result.error:
            _send(chat_id, reply_token, f"⚠️ {result.error}", messaging_api)
        else:
            new_tokens = (result.input_tokens or 0) + (result.output_tokens or 0)
            await sessions.save(
                session_key,
                session_id=result.session_id or existing_session_id or "",
                domain="line",
                token_count=existing_tokens + new_tokens,
            )
            _send(chat_id, reply_token, result.text or "✅ 對話已整理。", messaging_api)
        return True

    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def handle_line_message(
    event: "MessageEvent",
    runner: "ClaudeRunner",
    sessions: "SessionStore",
    messaging_api: "MessagingApi",
) -> None:
    """Dispatcher: resolve context, handle commands, then process message."""
    user_id: str = event.source.user_id
    session_key, prompt, chat_id = _resolve_context(event)

    # Fast path: Rich Menu commands (no Claude invocation)
    if event.message.text.strip().lower() in _LINE_COMMANDS:
        await _handle_line_command(
            event.message.text, session_key,
            event.reply_token, chat_id, sessions, runner, messaging_api,
        )
        return

    await _process_message(
        prompt=prompt,
        session_key=session_key,
        chat_id=chat_id,
        user_id=user_id,
        reply_token=event.reply_token,
        runner=runner,
        sessions=sessions,
        messaging_api=messaging_api,
    )


async def _process_message(
    prompt: str,
    session_key: str,
    chat_id: str,
    user_id: str,
    reply_token: str,
    runner: "ClaudeRunner",
    sessions: "SessionStore",
    messaging_api: "MessagingApi",
) -> None:
    """Shared message processing: get session → run Claude → send → save."""
    # 1. Get existing session
    row = await sessions.get(session_key)
    existing_session_id = row["session_id"] if row else None
    existing_tokens = row["token_count"] if row else 0

    # 2. Show loading animation (DM only — LINE API does not support group chats)
    if not session_key.startswith("line:group:"):
        try:
            messaging_api.show_loading_animation(
                ShowLoadingAnimationRequest(chat_id=chat_id, loading_seconds=60)
            )
        except Exception:
            logger.warning("show_loading_animation failed (non-fatal)", exc_info=True)

    # 3. Run Claude
    try:
        result, effective_session_id = await _run_with_recovery(
            runner, sessions, session_key, prompt, existing_session_id
        )
    except Exception:
        logger.exception("runner.run() raised an exception for session %s", session_key)
        _send(chat_id, reply_token, "⚠️ 出了點問題，請再試一次。", messaging_api)
        return

    # 4. Send response (reply_token first, push to chat_id as fallback)
    _send(chat_id, reply_token, result.text or "⚠️ (no response)", messaging_api)

    # 5. Save session
    new_tokens = (result.input_tokens or 0) + (result.output_tokens or 0)
    await sessions.save(
        session_key,
        session_id=effective_session_id,
        domain="line",
        token_count=existing_tokens + new_tokens,
    )


# ---------------------------------------------------------------------------
# Send helper
# ---------------------------------------------------------------------------

def _send(chat_id: str, reply_token: str, text: str, messaging_api: "MessagingApi") -> None:
    """Try reply_token first; fall back to push_message to chat_id."""
    try:
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text)],
            )
        )
    except ApiException:
        logger.info("reply_token expired, falling back to push_message to %s", chat_id)
        try:
            messaging_api.push_message(
                PushMessageRequest(to=chat_id, messages=[TextMessage(text=text)])
            )
        except Exception:
            logger.exception("push_message also failed for chat_id %s", chat_id)
    except Exception:
        logger.warning("reply_token failed with unexpected error", exc_info=True)
        try:
            messaging_api.push_message(
                PushMessageRequest(to=chat_id, messages=[TextMessage(text=text)])
            )
        except Exception:
            logger.exception("push_message also failed for chat_id %s", chat_id)


# ---------------------------------------------------------------------------
# Heartbeat push
# ---------------------------------------------------------------------------

def push_to_line(text: str, messaging_api: "MessagingApi") -> None:
    """Push text to the LINE user configured in LINE_USER_ID env var.

    Used by the heartbeat scheduler for proactive messages.
    """
    user_id = os.environ["LINE_USER_ID"]
    messaging_api.push_message(
        PushMessageRequest(
            to=user_id,
            messages=[TextMessage(text=text)],
        )
    )
