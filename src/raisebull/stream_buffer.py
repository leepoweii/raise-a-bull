"""Coalescing buffer for progressive Discord message streaming.

Inspired by OpenClaw's blockStreamingCoalesce:
- Accumulates text until min_chars threshold
- Flushes on idle timeout (no new chunks for idle_ms)
- Starts new message when current exceeds max_chars
"""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any, Awaitable, Callable, Optional, Protocol


class EditableMessage(Protocol):
    """Minimal interface for a Discord-like message that can be edited."""

    async def edit(self, content: str) -> None: ...


@dataclass
class CoalesceConfig:
    min_chars: int = 1500
    idle_ms: int = 1000
    max_chars: int = 2000


class StreamBuffer:
    """Accumulates text and flushes to Discord via send/edit."""

    def __init__(
        self,
        config: CoalesceConfig,
        send_fn: Callable[[str], Awaitable[Any]],
    ) -> None:
        self.config = config
        self.send_fn = send_fn
        self.buffer: str = ""
        self.sent_text: str = ""
        self.current_message: Optional[Any] = None
        self._last_append: float = 0.0

    async def append(self, text: str) -> None:
        """Add text to buffer; auto-flush if threshold reached."""
        self.buffer += text
        self._last_append = monotonic()
        if len(self.buffer) >= self.config.min_chars:
            await self.flush()

    async def check_idle(self) -> None:
        """Flush if idle timeout has elapsed since last append."""
        if not self.buffer or self._last_append == 0.0:
            return
        elapsed_ms = (monotonic() - self._last_append) * 1000
        if elapsed_ms >= self.config.idle_ms:
            await self.flush()

    async def flush(self) -> None:
        """Send or edit message with accumulated buffer content."""
        if not self.buffer:
            return

        new_total = self.sent_text + self.buffer

        if self.current_message is None:
            self.current_message = await self.send_fn(self.buffer)
            self.sent_text = self.buffer
        elif len(new_total) <= self.config.max_chars:
            await self.current_message.edit(content=new_total)
            self.sent_text = new_total
        else:
            self.current_message = await self.send_fn(self.buffer)
            self.sent_text = self.buffer

        self.buffer = ""

    async def finalize(self) -> None:
        """Flush any remaining buffered text."""
        await self.flush()
