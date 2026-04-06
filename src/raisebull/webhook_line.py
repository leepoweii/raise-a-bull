"""LINE webhook handler for raise-a-bull.

Pattern: run Claude, try reply_token first, fall back to push_message if
the token has expired (LINE reply token TTL is ~30 s; Claude may take longer for complex requests).

Session scoping:
  - Group chat  → session_key = line:group:{group_id}, prompt prefixed with speaker user_id
  - DM (1:1)    → session_key = line:{user_id}, prompt sent as-is

Buffer behaviour:
  - Group chat + not @mentioned → buffer message, return early (no LLM call)
  - Group chat + @mentioned     → build prompt from buffer, LLM call, clear buffer
  - DM                          → always respond immediately (no buffer)
"""
from __future__ import annotations

import asyncio as _asyncio
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

    from raisebull.buffer import MessageBuffer
    from raisebull.runner import ClaudeRunner
    from raisebull.session import SessionStore

logger = logging.getLogger(__name__)

from raisebull.discord_bot import _run_with_recovery  # noqa: E402


_LINE_COMMANDS = {"/new", "/info", "/compact"}

# ---------------------------------------------------------------------------
# Per-channel asyncio locks (prevent interleaved group processing)
# ---------------------------------------------------------------------------

_line_locks: dict[str, _asyncio.Lock] = {}


def _get_line_lock(key: str) -> _asyncio.Lock:
    if key not in _line_locks:
        _line_locks[key] = _asyncio.Lock()
    return _line_locks[key]


# ---------------------------------------------------------------------------
# Trigger prefix (LINE groups can't @mention bots)
# ---------------------------------------------------------------------------

def _read_trigger_prefix(workspace: str) -> str:
    """Read line_trigger_prefix from settings. Default: '小牛兒'."""
    import json
    try:
        with open(os.path.join(workspace or "/app/workspace", "config", "settings.json")) as f:
            return json.load(f).get("line_trigger_prefix", "小牛兒")
    except Exception:
        return "小牛兒"


# ---------------------------------------------------------------------------
# @mention detection
# ---------------------------------------------------------------------------

def line_bot_is_mentioned(mention) -> bool:
    """Return True if the bot itself was @mentioned in a LINE message."""
    if not mention:
        return False
    for m in getattr(mention, "mentionees", []):
        if getattr(m, "is_self", False):
            return True
    return False


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
    buffer: "MessageBuffer | None" = None,
) -> None:
    """Dispatcher: resolve context, handle commands, then process message.

    Group chat behaviour (requires buffer):
      - Not @mentioned → insert into buffer, return (no LLM call).
      - @mentioned     → build prompt from buffer + mention text, call LLM,
                         then clear the buffer.
    DM behaviour: always call LLM immediately (buffer is bypassed).
    """
    from time import time as _time

    user_id: str = event.source.user_id
    session_key, prompt, chat_id = _resolve_context(event)
    raw_text: str = event.message.text.strip()

    # Fast path: Rich Menu commands (no Claude invocation)
    if raw_text.lower() in _LINE_COMMANDS:
        await _handle_line_command(
            event.message.text, session_key,
            event.reply_token, chat_id, sessions, runner, messaging_api,
        )
        return

    is_group = event.source.type == "group"

    if is_group and buffer is not None:
        mention = getattr(event.message, "mention", None)
        is_mentioned = line_bot_is_mentioned(mention)

        # Fallback: text prefix trigger (LINE can't @mention bots in groups)
        # Reads line_trigger_prefix from settings (default: "小牛兒")
        trigger_prefix = _read_trigger_prefix(runner.workspace)
        prefix_triggered = raw_text.startswith(trigger_prefix) if trigger_prefix else False

        if not is_mentioned and not prefix_triggered:
            # Silent: buffer only, no LLM
            await buffer.insert(session_key, user_id, raw_text, _time())
            return

        # Active: strip mention/prefix to get actual request
        if is_mentioned:
            mention_text = _strip_self_mention(raw_text, mention)
        else:
            # Strip prefix trigger from text
            mention_text = raw_text[len(trigger_prefix):].strip() or "Hello"

        async with _get_line_lock(session_key):
            buffer_time = buffer.read_buffer_time(runner.workspace)
            full_prompt = await buffer.build_prompt(
                session_key, mention_text, buffer_time_minutes=buffer_time
            )
            await _process_message(
                prompt=full_prompt,
                session_key=session_key,
                chat_id=chat_id,
                user_id=user_id,
                reply_token=event.reply_token,
                runner=runner,
                sessions=sessions,
                messaging_api=messaging_api,
            )
            await buffer.delete_channel(session_key)
        return

    # DM (or group with no buffer configured): always respond immediately
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


def _strip_self_mention(text: str, mention) -> str:
    """Remove the bot's own @mention token from text.

    LINE mention objects carry an ``index`` (char offset) and ``length``
    for each mentionee.  We remove self-mention spans so the LLM only
    sees the actual question, not the raw @bot token.
    """
    if not mention:
        return text
    # Collect (index, length) for is_self mentionees, sorted reverse so we
    # can splice from the end without disturbing earlier indices.
    spans = sorted(
        [
            (getattr(m, "index", None), getattr(m, "length", None))
            for m in getattr(mention, "mentionees", [])
            if getattr(m, "is_self", False)
            and getattr(m, "index", None) is not None
            and getattr(m, "length", None) is not None
        ],
        reverse=True,
    )
    for start, length in spans:
        text = text[:start] + text[start + length :]
    return text.strip()


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

    # 5. Save session (with display name from LINE profile)
    session_name = None
    try:
        if session_key.startswith("line:group:"):
            session_name = "LINE Group"
        else:
            profile = messaging_api.get_profile(user_id)
            session_name = profile.display_name
    except Exception:
        pass  # name is optional, don't fail on profile lookup

    new_tokens = (result.input_tokens or 0) + (result.output_tokens or 0)
    await sessions.save(
        session_key,
        session_id=effective_session_id,
        domain="line",
        token_count=existing_tokens + new_tokens,
        name=session_name,
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


# ---------------------------------------------------------------------------
# Attachment handler
# ---------------------------------------------------------------------------

from raisebull.parsers.router import process_attachment
from raisebull.parsers.vision import create_vision_client

_vision_client_line = create_vision_client()


async def handle_line_attachment(
    event: "MessageEvent",
    runner: "ClaudeRunner",
    sessions: "SessionStore",
    messaging_api: "MessagingApi",
    blob_api,
) -> None:
    """Handle image/file attachments from LINE."""
    # Cannot use _resolve_context() — image/file messages have no .text attribute
    source = event.source
    user_id: str = source.user_id
    if source.type == "group":
        session_key = f"line:group:{source.group_id}"
        chat_id = source.group_id
    else:
        session_key = f"line:{user_id}"
        chat_id = user_id

    # Download content from LINE
    try:
        message_id = event.message.id
        content_response = blob_api.get_message_content(message_id)
        file_bytes = content_response

        # Determine filename — LINE does not provide MIME type,
        # so router will fall back to extension-based classification.
        msg = event.message
        if hasattr(msg, "file_name") and msg.file_name:
            filename = msg.file_name
            content_type = ""  # LINE FileMessageContent has no content_type field
        else:
            # Image message — no filename, use message_id
            filename = f"{message_id}.jpg"
            content_type = "image/jpeg"

    except Exception:
        logger.exception("Failed to download LINE content %s", event.message.id)
        _send(chat_id, event.reply_token, "⚠️ 無法下載附件", messaging_api)
        return

    # Process attachment
    try:
        filepath, preview = await process_attachment(
            file_bytes, filename, content_type,
            session_id=session_key,
            workspace=runner.workspace,
            vision_client=_vision_client_line,
        )

        prompt = (
            f"用戶上傳了 {filename}，已解析存放在：{filepath}\n"
            f"請用 Read 工具查看完整內容。\n"
            f"前 200 字預覽：\n{preview}"
        )

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
    except Exception:
        logger.exception("Failed to process LINE attachment")
        _send(chat_id, event.reply_token, "⚠️ 附件處理失敗", messaging_api)
