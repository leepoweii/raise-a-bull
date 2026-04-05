"""Heartbeat — APScheduler proactive push.

Periodically pokes ClaudeRunner with the current time.
ClaudeRunner reads heartbeat.md and executes due tasks.
Channel messages ([#channel-name] prefix) are routed to Discord.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from raisebull.runner import ClaudeRunner
from raisebull.session import SessionStore

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None

HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "300"))
MAX_DAILY_TRIGGERS = int(os.environ.get("MAX_DAILY_HEARTBEAT_TRIGGERS", "20"))

_last_heartbeat_response: Optional[str] = None
_last_heartbeat_time: Optional[float] = None


def build_heartbeat_prompt(
    now: str, day: str, time_str: str, last_run: str,
    heartbeat_path: str, lastrun_path: str,
) -> str:
    return (
        f"現在是 {now}（{day}）{time_str}。上次心跳：{last_run}。\n\n"
        "請執行以下步驟：\n"
        f"1. 讀取 {heartbeat_path} 了解排程任務\n"
        f"2. 讀取 {lastrun_path} 了解上次執行時間\n"
        "3. 判斷哪些任務到期（當前時間 >= 排程時間 且 今天尚未執行）\n"
        "4. 用現有技能執行到期任務\n"
        f"5. 執行完後更新 {lastrun_path}\n"
        "6. 【重要】每個要通知的訊息，必須用這個格式輸出：\n"
        "   [#management] 訊息內容\n"
        "   [#shipping] 訊息內容\n"
        "   [#daily-ops] 訊息內容\n"
        "   沒有 [#頻道名] 前綴的訊息不會被發送到 Discord。\n"
        "7. 如果在靜默時段（22:00-08:00），除非緊急警報否則不發通知\n"
    )


def parse_channel_messages(text: str) -> list[tuple[str, str]]:
    """Extract [#channel-name] prefixed messages. Supports multi-line bodies."""
    parts = re.split(r"\[#([\w-]+)\]\s*", text)
    results: list[tuple[str, str]] = []
    for i in range(1, len(parts) - 1, 2):
        channel = parts[i]
        body = parts[i + 1].strip()
        if body:
            results.append((channel, body))
    return results


async def _heartbeat_tick(runner: ClaudeRunner, sessions: SessionStore, push_fn=None) -> None:
    global _last_heartbeat_response, _last_heartbeat_time
    now = datetime.now()
    workspace = runner.workspace or "/app/workspace"

    prompt = build_heartbeat_prompt(
        now=now.strftime("%Y-%m-%d %H:%M:%S"), day=now.strftime("%A"),
        time_str=now.strftime("%H:%M"), last_run=str(_last_heartbeat_time or "never"),
        heartbeat_path=f"{workspace}/heartbeat/heartbeat.md",
        lastrun_path=f"{workspace}/heartbeat/last-run.json",
    )

    key = "heartbeat:system"
    session = await sessions.get(key)
    session_id = session["session_id"] if session else None

    try:
        result = await runner.run(prompt, session_id=session_id, timeout_seconds=600.0)
        if result.error:
            logger.error("Heartbeat error: %s", result.error)
            return

        await sessions.save(
            key, session_id=result.session_id or session_id or "",
            domain="heartbeat",
            token_count=(session["token_count"] if session else 0) + (result.input_tokens or 0) + (result.output_tokens or 0),
            name="Heartbeat",
        )

        _last_heartbeat_response = result.text
        _last_heartbeat_time = now.timestamp()

        if result.text and push_fn:
            for channel_name, msg_text in parse_channel_messages(result.text):
                try:
                    await push_fn(channel_name, msg_text)
                    logger.info("Heartbeat → #%s: %s", channel_name, msg_text[:50])
                except Exception as push_err:
                    logger.warning("Heartbeat push to #%s failed: %s", channel_name, push_err)

        logger.info("Heartbeat tick completed: %d chars response", len(result.text or ""))
    except Exception:
        logger.exception("Heartbeat tick failed")


def start_heartbeat(runner: ClaudeRunner, sessions: SessionStore, push_fn=None) -> None:
    global _scheduler
    if HEARTBEAT_INTERVAL <= 0:
        logger.info("Heartbeat disabled (interval <= 0)")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _heartbeat_tick, "interval", seconds=HEARTBEAT_INTERVAL,
        args=[runner, sessions, push_fn], max_instances=1,
    )
    _scheduler.start()
    logger.info("Heartbeat started: interval=%ds", HEARTBEAT_INTERVAL)


async def run_event_check(runner: ClaudeRunner, sessions: SessionStore, push_fn=None) -> None:
    await _heartbeat_tick(runner, sessions, push_fn=push_fn)
