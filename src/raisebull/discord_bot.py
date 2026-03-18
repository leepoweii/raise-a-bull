"""Discord bot for raise-a-bull.

Provides a Discord bot with slash commands and @mention-based conversation.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Running bot instance — set by run_discord_bot(), read by get_bot()
_running_bot: "commands.Bot | None" = None


def get_bot() -> "commands.Bot | None":
    """Return the running discord.py Bot instance, or None if not started."""
    return _running_bot

import discord
from discord.ext import commands

from raisebull.runner import ClaudeRunner
from raisebull.session import SessionStore

# Channel name → domain mappings
_CHANNEL_DOMAIN_MAP = {
    "morning": "daily",
    "reminders": "daily",
    "meta": "admin",
}

CHUNK_SIZE = 1900


def extract_domain_from_channel(name: str) -> str:
    """Map a Discord channel name to a session domain."""
    return _CHANNEL_DOMAIN_MAP.get(name, "general")


def _split_message(text: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Split *text* into chunks of at most *chunk_size* characters."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:chunk_size])
        text = text[chunk_size:]
    return chunks


def create_bot(runner: ClaudeRunner, sessions: SessionStore) -> commands.Bot:
    """Create and configure the Discord bot."""
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    guild_id_str = os.environ.get("DISCORD_GUILD_ID", "")
    guild_ids = [int(guild_id_str)] if guild_id_str else []

    # ------------------------------------------------------------------ #
    # on_message: respond to all messages                                  #
    # ------------------------------------------------------------------ #

    @bot.event
    async def on_message(message: discord.Message) -> None:
        if message.author.bot:
            return

        channel_name = getattr(message.channel, "name", "general")
        domain = extract_domain_from_channel(channel_name)
        key = f"discord:{message.channel.id}"

        session = await sessions.get(key)
        session_id: Optional[str] = session["session_id"] if session else None

        # Strip the @mention from the prompt
        prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not prompt:
            prompt = "Hello"

        try:
            async with message.channel.typing():
                result = await runner.run(prompt, session_id=session_id)
        except Exception:
            logger.exception("runner.run() failed in on_message for channel %s", key)
            await message.reply("⚠️ 出了點問題，請再試一次。")
            return

        if result.error:
            await message.reply(f"⚠️ {result.error}")
            return

        # Save updated session (token count is cumulative)
        existing_tokens = session["token_count"] if session else 0
        await sessions.save(
            key,
            session_id=result.session_id or session_id or "",
            domain=domain,
            token_count=existing_tokens + (result.input_tokens or 0) + (result.output_tokens or 0),
        )

        # Send response, splitting if needed
        chunks = _split_message(result.text or "(no response)")
        first = True
        for chunk in chunks:
            if first:
                await message.reply(chunk)
                first = False
            else:
                await message.channel.send(chunk)

        await bot.process_commands(message)

    # ------------------------------------------------------------------ #
    # Slash commands                                                       #
    # ------------------------------------------------------------------ #

    @bot.tree.command(
        name="new-session",
        description="Clear the current session for this channel.",
        guilds=[discord.Object(id=g) for g in guild_ids],
    )
    async def new_session(interaction: discord.Interaction) -> None:
        key = f"discord:{interaction.channel_id}"
        await sessions.clear(key)
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
        session_name = f"{session['domain']}-{session['session_id'][:4]}"
        msg = (
            f"**Session info**\n"
            f"Name: {session_name}\n"
            f"Token count: {session['token_count']}\n"
            f"Domain: {session['domain']}\n"
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
        session_id: Optional[str] = session["session_id"] if session else None
        domain = session["domain"] if session else "general"

        result = await runner.run("/compact", session_id=session_id)

        if result.error:
            await interaction.followup.send(f"Error: {result.error}", ephemeral=True)
            return

        existing_tokens = session["token_count"] if session else 0
        await sessions.save(
            key,
            session_id=result.session_id or session_id or "",
            domain=domain,
            token_count=existing_tokens + result.input_tokens + result.output_tokens,
        )
        await interaction.followup.send(result.text or "Compacted.", ephemeral=True)

    @bot.event
    async def on_ready() -> None:
        for guild_id in guild_ids:
            guild = discord.Object(id=guild_id)
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
        print(f"Callie bot ready as {bot.user}")

    return bot


async def run_discord_bot(runner: ClaudeRunner, sessions: SessionStore) -> None:
    """Start the Discord bot using the DISCORD_BOT_TOKEN env var."""
    global _running_bot
    token = os.environ["DISCORD_BOT_TOKEN"]
    _running_bot = create_bot(runner, sessions)
    await _running_bot.start(token)
