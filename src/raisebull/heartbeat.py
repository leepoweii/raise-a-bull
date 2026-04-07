"""Heartbeat — APScheduler proactive push.

Periodically pokes ClaudeRunner with the current time.
ClaudeRunner reads heartbeat.md and executes due tasks.
Channel messages ([#channel-name] prefix) are routed to Discord.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from raisebull.runner import ClaudeRunner
from raisebull.session import SessionStore

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None

HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "300"))
MAX_DAILY_TRIGGERS = int(os.environ.get("MAX_DAILY_HEARTBEAT_TRIGGERS", "20"))
COMPACT_TOKEN_THRESHOLD = 50_000


def is_compact_eligible(
    session: dict,
    key: str = "",
    threshold: int = COMPACT_TOKEN_THRESHOLD,
) -> bool:
    """Check if a session should be compacted in the nightly job."""
    if key.startswith("heartbeat:"):
        return False
    if session["token_count"] <= threshold:
        return False
    last_compacted = session.get("last_compacted_at")
    if last_compacted and session["last_active"] <= last_compacted:
        return False  # No new activity since last compact
    return True


def _coerce_threshold(value) -> int | None:
    """Convert raw value to a positive int, or return None if invalid/non-positive."""
    try:
        n = int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return None
    if n <= 0:
        return None
    return n


def _read_threshold(workspace: str) -> int:
    """Resolve nightly-compact threshold.

    Precedence: settings.json > NIGHTLY_COMPACT_THRESHOLD env > 50000.
    Invalid (non-numeric, zero, negative) values fall through to the next layer.
    """
    settings_path = Path(workspace) / "config" / "settings.json"
    if settings_path.exists():
        try:
            stored = json.loads(settings_path.read_text(encoding="utf-8"))
            from_settings = _coerce_threshold(stored.get("nightly_compact_threshold"))
            if from_settings is not None:
                return from_settings
        except (json.JSONDecodeError, OSError):
            pass

    from_env = _coerce_threshold(os.environ.get("NIGHTLY_COMPACT_THRESHOLD"))
    if from_env is not None:
        return from_env

    return COMPACT_TOKEN_THRESHOLD


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

    try:
        # Fresh start each tick — no session persistence for heartbeat.
        # Prevents token accumulation (heartbeat pushes results to channels,
        # so conversation history is not needed across ticks).
        result = await runner.run(prompt, session_id=None, timeout_seconds=600.0)
        if result.error:
            logger.error("Heartbeat error: %s", result.error)
            return

        await sessions.save(
            key, session_id=result.session_id or "",
            domain="heartbeat",
            token_count=(result.input_tokens or 0) + (result.output_tokens or 0),
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


async def nightly_compact(runner: ClaudeRunner, sessions: SessionStore, buffer=None) -> None:
    """Run nightly compact + consolidate. Called by scheduler at configured hour."""
    from datetime import timezone

    all_sessions = await sessions.list_all()
    eligible = [s for s in all_sessions if is_compact_eligible(s, key=s["key"])]

    if not eligible:
        logger.info("Nightly compact: no eligible sessions")
        return

    for s in eligible:
        key = s["key"]
        session_id = s["session_id"]
        logger.info("Nightly compact: %s (tokens=%d)", key, s["token_count"])

        # Step 1: inject unprocessed buffer into session
        if buffer:
            msgs = await buffer.get_all(key)
            if msgs:
                prompt = await buffer.build_prompt(key, "(nightly compact — injecting buffered messages)")
                inject_result = await runner.run(prompt, session_id=session_id, timeout_seconds=300.0)
                if not inject_result.error:
                    # Only clear buffer once we know the injection succeeded
                    await buffer.delete_channel(key)
                    session_id = inject_result.session_id or session_id
                else:
                    logger.warning("Buffer injection failed for %s, keeping buffer: %s", key, inject_result.error)

        # Step 2: compact
        result = await runner.run("/compact", session_id=session_id, timeout_seconds=300.0)
        if result.error:
            logger.error("Compact failed for %s: %s", key, result.error)
            continue

        # Step 3: update DB — save new session_id, then stamp last_compacted_at >= last_active
        new_session_id = result.session_id or session_id
        await sessions.save(
            key, session_id=new_session_id, domain=s["domain"],
            token_count=result.output_tokens or s["token_count"],
        )
        # Capture timestamp AFTER save() so last_compacted_at >= last_active,
        # preventing is_compact_eligible() from treating the compact itself as new activity.
        now = datetime.now(timezone.utc).isoformat()
        await sessions.update_compacted_at(key, now)

    # Step 4: consolidate — one LLM call to update memory
    summary_parts = [f"Session {s['key']}: {s['token_count']} tokens" for s in eligible]
    consolidate_prompt = (
        "你是記憶整理助理。以下 session 剛剛被 compact 了。\n"
        "請讀取各 session 的最新狀態，整理重要資訊，更新 memory/ 目錄下的相關檔案。\n"
        "你可以自行決定要寫入哪些檔案。\n\n"
        + "\n".join(summary_parts)
    )
    await runner.run(consolidate_prompt, session_id=None, timeout_seconds=600.0)
    logger.info("Nightly consolidate complete")


def start_heartbeat(runner: ClaudeRunner, sessions: SessionStore, push_fn=None, buffer=None) -> None:
    global _scheduler
    if HEARTBEAT_INTERVAL <= 0:
        logger.info("Heartbeat disabled (interval <= 0)")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _heartbeat_tick, "interval", seconds=HEARTBEAT_INTERVAL,
        args=[runner, sessions, push_fn], max_instances=1,
    )

    # Nightly compact job
    compact_hour = int(os.environ.get("NIGHTLY_COMPACT_HOUR", "3"))
    _scheduler.add_job(
        nightly_compact,
        "cron",
        hour=compact_hour,
        minute=0,
        args=[runner, sessions, buffer],
        id="nightly_compact",
    )
    logger.info("Nightly compact scheduled at %02d:00", compact_hour)

    _scheduler.start()
    logger.info("Heartbeat started: interval=%ds", HEARTBEAT_INTERVAL)


async def run_event_check(runner: ClaudeRunner, sessions: SessionStore, push_fn=None) -> None:
    await _heartbeat_tick(runner, sessions, push_fn=push_fn)
