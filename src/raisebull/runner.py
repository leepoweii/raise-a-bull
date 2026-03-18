"""
ClaudeRunner: wraps `claude -p --output-format stream-json` as an async subprocess.
"""

from __future__ import annotations

import asyncio
import json
from asyncio.subprocess import DEVNULL, PIPE
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


ALLOWED_TOOLS = "Read,Write,Edit,Glob,Grep,Bash"

AsyncChunkCallback = Callable[[str], Awaitable[None]]


@dataclass
class RunResult:
    text: str = ""
    session_id: Optional[str] = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None


class ClaudeRunner:
    """Executes `claude -p` and parses its stream-json output."""

    def __init__(self, claude_bin: str = "claude", workspace: str = "", model: str = "claude-sonnet-4-6") -> None:
        self.claude_bin = claude_bin
        self.workspace = workspace
        self.model = model

    # ------------------------------------------------------------------
    # Command building
    # ------------------------------------------------------------------

    def _build_cmd(self, prompt: str, session_id: Optional[str]) -> list[str]:
        cmd = [
            self.claude_bin,
            "-p", prompt,
            "--output-format", "stream-json",
            "--verbose",
            "--allowedTools", ALLOWED_TOOLS,
            "--model", self.model,
        ]
        if self.workspace:
            cmd += ["--add-dir", self.workspace]
        if session_id:
            cmd += ["--resume", session_id]
        return cmd

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text_chunks(event: dict) -> list[str]:
        """Extract text strings from an assistant event's content array."""
        return [
            block["text"]
            for block in event.get("message", {}).get("content", [])
            if block.get("type") == "text"
        ]

    def _parse_lines(self, lines: list[bytes]) -> RunResult:
        result = RunResult()
        text_parts: list[str] = []

        for raw in lines:
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")

            if event_type == "assistant":
                text_parts.extend(self._extract_text_chunks(event))

            elif event_type == "result":
                result.session_id = event.get("session_id")
                result.cost_usd = event.get("cost_usd", 0.0)
                usage = event.get("usage", {})
                result.input_tokens = usage.get("input_tokens", 0)
                result.output_tokens = usage.get("output_tokens", 0)

        result.text = "".join(text_parts)
        return result

    # ------------------------------------------------------------------
    # Async run
    # ------------------------------------------------------------------

    async def run(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        on_chunk: Optional[AsyncChunkCallback] = None,
        timeout_seconds: float = 120.0,
    ) -> RunResult:
        cmd = self._build_cmd(prompt, session_id)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=DEVNULL,
            stdout=PIPE,
            stderr=PIPE,
            cwd=self.workspace if self.workspace else None,
        )

        # Drain stderr in the background to prevent pipe buffer deadlock when
        # stderr output exceeds the OS pipe buffer (~64 KB).
        stderr_task = asyncio.create_task(proc.stderr.read())

        raw_lines: list[bytes] = []
        timed_out = False
        try:
            async with asyncio.timeout(timeout_seconds):
                async for line in proc.stdout:
                    line = line.rstrip(b"\n")
                    if not line:
                        continue
                    raw_lines.append(line)

                    # Fire on_chunk callback for assistant text as it streams
                    if on_chunk is not None:
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if event.get("type") == "assistant":
                            for chunk in self._extract_text_chunks(event):
                                if chunk:
                                    await on_chunk(chunk)

                await proc.wait()
        except TimeoutError:
            timed_out = True
            proc.kill()
            await proc.wait()
        except BaseException:
            proc.kill()
            await proc.wait()
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass
            raise
        finally:
            pass

        # Cancel stderr drain if we timed out (we don't need the output).
        if timed_out:
            stderr_task.cancel()
            try:
                await stderr_task
            except (asyncio.CancelledError, Exception):
                pass
            return RunResult(error=f"claude -p timed out after {timeout_seconds}s")

        # Normal completion: collect stderr output.
        stderr_output = await stderr_task

        result = self._parse_lines(raw_lines)
        if proc.returncode != 0:
            result.error = stderr_output.decode(errors="replace").strip() or f"exit {proc.returncode}"
            result.text = ""
        return result
