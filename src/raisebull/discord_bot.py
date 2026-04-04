"""Discord bot for raise-a-bull.

Three-tier response model (from raise-a-calf):
  1. Silent  — records messages (no LLM call)
  2. Active  — @mention activates; bot responds to every message
  3. Timeout — after TIMEOUT seconds of inactivity, reverts to silent

Streaming: coalescing buffer (minChars 1500, idleMs 1000) for main response.
Traces: progressive thread messages (one per thinking/tool phase).
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from time import time
from typing import Optional

import discord
from discord.ext import commands

from raisebull.runner import ClaudeRunner, RunResult
from raisebull.session import SessionStore
from raisebull.trace import TraceStep
from raisebull.stream_buffer import CoalesceConfig, StreamBuffer
from raisebull.parsers.router import process_attachment
from raisebull.parsers.vision import create_vision_client

logger = logging.getLogger(__name__)

TIMEOUT = int(os.environ.get("AUTO_REPLY_TIMEOUT", "180"))
CHUNK_SIZE = 1900

_CHANNEL_DOMAIN_MAP = {
    "morning": "daily",
    "reminders": "daily",
    "meta": "admin",
}


# ------------------------------------------------------------------
# Three-tier state machine
# ------------------------------------------------------------------

@dataclass
class ChannelState:
    active: bool = False
    last_active: float = field(default_factory=time)

    def on_mention(self) -> None:
        self.active = True
        self.last_active = time()

    def on_message(self) -> None:
        self.last_active = time()

    def check_timeout(self) -> None:
        if self.active and (time() - self.last_active > TIMEOUT):
            self.active = False


def should_respond(state: ChannelState, mentioned: bool) -> bool:
    """Pure check — no side effects. Caller handles state mutation."""
    state.check_timeout()
    if mentioned:
        return True
    return state.active


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def extract_domain_from_channel(name: str) -> str:
    return _CHANNEL_DOMAIN_MAP.get(name, "general")


def _split_message(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:chunk_size])
        text = text[chunk_size:]
    return chunks


# ------------------------------------------------------------------
# Stale session recovery helper (used by create_bot and tests)
# ------------------------------------------------------------------

async def _run_with_recovery(runner: "ClaudeRunner", sessions: "SessionStore", key: str, prompt: str, session_id: Optional[str]):
    """Run prompt, auto-recovering from a stale session_id.

    Returns (RunResult, effective_session_id).
    On stale session, clears DB entry and retries without --resume.
    """
    result = await runner.run(prompt, session_id=session_id)
    if result.stale_session:
        logger.info("Stale session detected for %s — clearing and retrying", key)
        await sessions.clear(key)
        result = await runner.run(prompt, session_id=None)
        session_id = None
    return result, result.session_id or session_id or ""


# ------------------------------------------------------------------
# Progressive thread traces
# ------------------------------------------------------------------

class ThreadTracer:
    def __init__(self, thread: discord.Thread) -> None:
        self.thread = thread
        self._thinking_msg: Optional[discord.Message] = None
        self._thinking_buf: str = ""
        self._tool_msg: Optional[discord.Message] = None
        self._last_tool_name: str = ""

    async def on_step(self, step: TraceStep) -> None:
        try:
            if step.step_type == "thinking":
                await self._handle_thinking(step.content)
            elif step.step_type == "tool_call":
                await self._flush_thinking()
                await self._handle_tool_call(step.content)
            elif step.step_type == "tool_result":
                await self._handle_tool_result(step.content)
            elif step.step_type == "text":
                await self._flush_thinking()
        except discord.HTTPException as e:
            logger.warning("Thread trace failed: %s", e)

    async def _handle_thinking(self, text: str) -> None:
        self._thinking_buf += text
        display = self._thinking_buf[:1900]
        if self._thinking_msg is None:
            self._thinking_msg = await self.thread.send(f"🧠 {display}")
        else:
            await self._thinking_msg.edit(content=f"🧠 {display}")

    async def _flush_thinking(self) -> None:
        self._thinking_msg = None
        self._thinking_buf = ""

    async def _handle_tool_call(self, content: dict) -> None:
        name = content.get("name", "?")
        input_summary = str(content.get("input", ""))[:150]
        self._last_tool_name = name
        self._tool_msg = await self.thread.send(f"🔧 **{name}** → `{input_summary}`")

    async def _handle_tool_result(self, content: str) -> None:
        if self._tool_msg is None:
            return
        summary = str(content)[:200]
        if len(str(content)) > 200:
            summary += "..."
        await self._tool_msg.edit(
            content=f"🔧 **{self._last_tool_name}** → 📄 {summary}"
        )
        self._tool_msg = None


# ------------------------------------------------------------------
# Bot factory
# ------------------------------------------------------------------

_running_bot: Optional[commands.Bot] = None


def get_bot() -> Optional[commands.Bot]:
    return _running_bot


def create_bot(runner: ClaudeRunner, sessions: SessionStore) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    guild_id_str = os.environ.get("DISCORD_GUILD_ID", "")
    guild_ids = [int(guild_id_str)] if guild_id_str else []

    channel_states: dict[str, ChannelState] = {}
    _vision_client = create_vision_client()

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return

        channel_name = getattr(message.channel, "name", "general")
        domain = extract_domain_from_channel(channel_name)
        key = f"discord:{message.channel.id}"

        state = channel_states.setdefault(key, ChannelState())
        mentioned = bot.user in message.mentions if bot.user else False

        if not should_respond(state, mentioned):
            return

        # Confirmed response — now mutate state
        if mentioned:
            state.on_mention()
        else:
            state.on_message()

        prompt = message.content
        if bot.user:
            prompt = prompt.replace(f"<@{bot.user.id}>", "").strip()
        if not prompt and not message.attachments:
            prompt = "Hello"

        # Process attachments
        attachment_parts = []
        for att in message.attachments:
            try:
                file_bytes = await att.read()
                filepath, preview = await process_attachment(
                    file_bytes, att.filename, att.content_type or "",
                    session_id=key, workspace=runner.workspace,
                    vision_client=_vision_client,
                )
                attachment_parts.append(
                    f"用戶上傳了 {att.filename}，已解析存放在：{filepath}\n"
                    f"請用 Read 工具查看完整內容。\n"
                    f"前 200 字預覽：\n{preview}"
                )
            except Exception:
                logger.exception("Failed to process attachment %s", att.filename)
                attachment_parts.append(f"(附件 {att.filename} 處理失敗)")

        if attachment_parts:
            prompt = "\n\n---\n\n".join(attachment_parts) + "\n\n" + (prompt or "")
            prompt = prompt.strip()

        session = await sessions.get(key)
        session_id: Optional[str] = session["session_id"] if session else None

        try:
            # Eager placeholder + thread creation
            reply_msg = await message.reply("⏳")
            thread: Optional[discord.Thread] = None
            tracer: Optional[ThreadTracer] = None
            try:
                from datetime import datetime
                thread = await reply_msg.create_thread(
                    name=f"🧠 Trace {datetime.now().strftime('%H:%M')}",
                    auto_archive_duration=60,
                )
                tracer = ThreadTracer(thread)
            except discord.Forbidden:
                logger.warning("Cannot create trace thread — missing permissions")

            # Coalescing buffer (edits placeholder on first flush)
            first_edit = True

            async def send_or_edit(text: str):
                nonlocal first_edit
                if first_edit:
                    first_edit = False
                    await reply_msg.edit(content=text)
                    return reply_msg
                else:
                    return await message.channel.send(text)

            buffer = StreamBuffer(config=CoalesceConfig(), send_fn=send_or_edit)

            # Idle checker
            idle_running = True

            async def idle_checker():
                while idle_running:
                    await asyncio.sleep(buffer.config.idle_ms / 1000.0)
                    await buffer.check_idle()

            idle_task = asyncio.create_task(idle_checker())

            async def on_trace(step: TraceStep) -> None:
                if step.step_type == "text":
                    await buffer.append(step.content)
                elif tracer is not None:
                    await tracer.on_step(step)

            # Run with inline stale session recovery
            async def run_with_trace():
                nonlocal first_edit
                result = await runner.run(
                    prompt, session_id=session_id,
                    on_trace=on_trace, timeout_seconds=300.0,
                )
                if result.stale_session:
                    logger.info("Stale session for %s — clearing and retrying", key)
                    await sessions.clear(key)
                    buffer.buffer = ""
                    buffer.sent_text = ""
                    buffer.current_message = None
                    first_edit = True
                    await reply_msg.edit(content="⏳")
                    result = await runner.run(
                        prompt, session_id=None,
                        on_trace=on_trace, timeout_seconds=300.0,
                    )
                effective_sid = result.session_id or session_id or ""
                return result, effective_sid

            async with message.channel.typing():
                result, effective_sid = await run_with_trace()

            # Stop idle checker
            idle_running = False
            idle_task.cancel()
            try:
                await idle_task
            except asyncio.CancelledError:
                pass

            # Check error BEFORE finalizing buffer
            if result.error:
                await reply_msg.edit(content=f"⚠️ {result.error}")
                return

            await buffer.finalize()

            if first_edit and result.text:
                await reply_msg.edit(content=result.text[:2000])

            existing_tokens = session["token_count"] if session else 0
            await sessions.save(
                key,
                session_id=effective_sid,
                domain=domain,
                token_count=existing_tokens + (result.input_tokens or 0) + (result.output_tokens or 0),
            )

        except Exception:
            logger.exception("Error in on_message for %s", key)
            await message.reply("⚠️ 出了點問題，請再試一次。")

        await bot.process_commands(message)

    @bot.tree.command(
        name="new-session",
        description="Clear the current session for this channel.",
        guilds=[discord.Object(id=g) for g in guild_ids],
    )
    async def new_session(interaction: discord.Interaction) -> None:
        key = f"discord:{interaction.channel_id}"
        await sessions.clear(key)
        channel_states.pop(key, None)
        await interaction.response.send_message("Session cleared.", ephemeral=True)

    @bot.tree.command(
        name="session-info",
        description="Show current session info for this channel.",
        guilds=[discord.Object(id=g) for g in guild_ids],
    )
    async def session_info(interaction: discord.Interaction) -> None:
        key = f"discord:{interaction.channel_id}"
        session = await sessions.get(key)
        if session is None:
            await interaction.response.send_message("No active session.", ephemeral=True)
            return
        state = channel_states.get(key, ChannelState())
        msg = (
            f"**Session info**\n"
            f"Token count: {session['token_count']}\n"
            f"Domain: {session['domain']}\n"
            f"Active: {'✅' if state.active else '❌ (silent)'}\n"
            f"Last active: {session['last_active']}"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(
        name="compact",
        description="Compact the current session context.",
        guilds=[discord.Object(id=g) for g in guild_ids],
    )
    async def compact(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        key = f"discord:{interaction.channel_id}"
        session = await sessions.get(key)
        session_id_val: Optional[str] = session["session_id"] if session else None
        domain_val = session["domain"] if session else "general"

        result = await runner.run("/compact", session_id=session_id_val)

        if result.error:
            await interaction.followup.send(f"Error: {result.error}", ephemeral=True)
            return

        existing_tokens = session["token_count"] if session else 0
        await sessions.save(
            key,
            session_id=result.session_id or session_id_val or "",
            domain=domain_val,
            token_count=existing_tokens + (result.input_tokens or 0) + (result.output_tokens or 0),
        )
        await interaction.followup.send(result.text or "Compacted.", ephemeral=True)

    @bot.event
    async def on_ready() -> None:
        for guild_id in guild_ids:
            guild = discord.Object(id=guild_id)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        print(f"Bot ready as {bot.user}")

    return bot


async def run_discord_bot(runner: ClaudeRunner, sessions: SessionStore) -> None:
    global _running_bot
    token = os.environ["DISCORD_BOT_TOKEN"]
    _running_bot = create_bot(runner, sessions)
    await _running_bot.start(token)
