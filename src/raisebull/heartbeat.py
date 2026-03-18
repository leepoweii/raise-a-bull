"""Heartbeat — proactive push via APScheduler. (v2 feature — stub in v1)"""
from __future__ import annotations


def start_heartbeat(runner, sessions) -> None:
    """Start the heartbeat scheduler. No-op in v1."""
    pass


async def run_event_check(runner, sessions) -> None:
    """Run one heartbeat tick. No-op in v1."""
    pass
