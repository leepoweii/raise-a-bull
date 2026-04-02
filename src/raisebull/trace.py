"""Parse Claude Code stream-json output into structured TraceStep events."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass
class TraceStep:
    """One step in the agent's reasoning/action chain."""

    step_type: str  # "thinking" | "tool_call" | "tool_result" | "text"
    content: Any  # str for thinking/text/tool_result, dict for tool_call
    timestamp: float = field(default_factory=time)


_PARSERS = {
    "thinking": lambda block: TraceStep("thinking", block["thinking"]),
    "tool_use": lambda block: TraceStep(
        "tool_call",
        {"name": block["name"], "input": block.get("input", {}), "id": block.get("id", "")},
    ),
    "tool_result": lambda block: TraceStep("tool_result", block.get("content", "")),
    "text": lambda block: TraceStep("text", block["text"]),
}


def parse_stream_event(raw_line: bytes) -> list[TraceStep]:
    """Parse one stream-json line into zero or more TraceSteps."""
    try:
        event = json.loads(raw_line)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []

    event_type = event.get("type")
    if event_type not in ("assistant", "user"):
        return []

    blocks = event.get("message", {}).get("content", [])
    if not isinstance(blocks, list):
        return []

    steps: list[TraceStep] = []
    for block in blocks:
        block_type = block.get("type", "")
        parser = _PARSERS.get(block_type)
        if parser:
            try:
                steps.append(parser(block))
            except (KeyError, TypeError):
                continue
    return steps
