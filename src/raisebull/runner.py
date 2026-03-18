"""Runner abstraction — wraps claude -p (and future runtimes)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunResult:
    text: str
    session_id: str | None = None


class BaseRunner:
    async def run(self, prompt: str, session_id: str | None = None) -> RunResult:
        raise NotImplementedError


class ClaudeRunner(BaseRunner):
    """Wraps `claude -p` with workspace directory injection."""

    def __init__(self, workspace_path: str | Path):
        self.workspace_path = str(workspace_path)

    async def run(self, prompt: str, session_id: str | None = None) -> RunResult:
        cmd = ["claude", "-p", "--add-dir", self.workspace_path]
        if session_id:
            cmd += ["--resume", session_id]
        cmd.append(prompt)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        text = stdout.decode().strip()

        # TODO: extract session_id from claude output
        return RunResult(text=text, session_id=session_id)
