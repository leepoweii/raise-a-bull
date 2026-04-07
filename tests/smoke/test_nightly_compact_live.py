"""Smoke test: nightly_compact with real Claude CLI.

Verifies the threshold gate works end-to-end:
- Session above threshold → compacted (new session_id, last_compacted_at stamped)
- Session below threshold → untouched

Run with:
    ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic \\
    ANTHROPIC_AUTH_TOKEN=<key> \\
    uv run pytest tests/smoke/test_nightly_compact_live.py -v -s

Costs ~2 Claude calls per invocation (1 /compact + 1 consolidate). The
below-threshold session never reaches the model.
"""
import asyncio
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

smoke = pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_BASE_URL") and os.environ.get("ANTHROPIC_AUTH_TOKEN")),
    reason="Requires ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN env vars",
)

THRESHOLD = 1000
SESSION_ABOVE = "web:smoke-above"
SESSION_BELOW = "web:smoke-below"
PORT_NAME = "nightly_compact_smoke"
PASSWORD = "smoke_nightly_compact_test"
# 2 real Claude calls (1× /compact + 1× consolidate). Each can take 60-120s on a
# slow link. 600s gives generous headroom — the test still bails fast if the
# trigger endpoint is broken because it polls every 3s and would never see
# last_compacted_at flip.
MAX_WAIT_SECONDS = 600
POLL_INTERVAL = 3


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Start a real uvicorn server with a low compact threshold."""
    tmp = tmp_path_factory.mktemp(PORT_NAME)
    workspace = tmp / "workspace"
    workspace.mkdir()
    for d in ("config", "context", "skills", "heartbeat"):
        (workspace / d).mkdir()

    # settings.json with low threshold so the seeded "above" session triggers
    (workspace / "config" / "settings.json").write_text(
        '{"nightly_compact_threshold": "' + str(THRESHOLD) + '"}'
    )
    # heartbeat.md must exist or the heartbeat scheduler errors
    (workspace / "heartbeat" / "heartbeat.md").write_text("## Smoke\n")
    (workspace / "heartbeat" / "last-run.json").write_text("{}")

    port = _find_free_port()
    sessions_db = str(tmp / "sessions.db")
    creds_db = str(tmp / "credentials.db")

    env = {
        **os.environ,
        "LINE_CHANNEL_SECRET": "dummy",
        "LINE_CHANNEL_ACCESS_TOKEN": "dummy",
        "DISCORD_BOT_TOKEN": "",
        # Long heartbeat so we don't conflict with our manual nightly trigger
        "HEARTBEAT_INTERVAL": "3600",
        "DB_PATH": sessions_db,
        "CREDENTIALS_DB_PATH": creds_db,
        "WORKSPACE": str(workspace),
        "ADMIN_PASSWORD": PASSWORD,
        "CLAUDE_MODEL": os.environ.get("ANTHROPIC_MODEL", "MiniMax-M2.7"),
    }

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "raisebull.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    base_url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            r = httpx.get(f"{base_url}/health", timeout=2)
            if r.status_code == 200:
                break
        except httpx.ConnectError:
            pass
        time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError("Server failed to start")

    client = httpx.Client(base_url=base_url, timeout=30)
    resp = client.post("/admin/api/auth", json={"password": PASSWORD})
    assert resp.status_code == 200, "smoke server login failed"

    yield {
        "base_url": base_url,
        "client": client,
        "workspace": workspace,
        "proc": proc,
        "sessions_db": sessions_db,
    }

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    client.close()


def _seed_session(db_path: str, key: str, session_id: str, token_count: int) -> None:
    """Insert a session row directly into SQLite (bypasses live SessionStore)."""
    import sqlite3
    last_active = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sessions "
            "(key, session_id, domain, last_active, token_count, name, last_compacted_at) "
            "VALUES (?, ?, 'web', ?, ?, ?, NULL)",
            (key, session_id, last_active, token_count, key.split(":")[-1]),
        )
        conn.commit()
    finally:
        conn.close()


def _read_session(db_path: str, key: str) -> dict | None:
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT key, session_id, token_count, last_active, last_compacted_at "
            "FROM sessions WHERE key = ?",
            (key,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _wait_for_compact(db_path: str, key: str, timeout: int = MAX_WAIT_SECONDS) -> dict:
    """Poll until the session has a non-null last_compacted_at, or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        row = _read_session(db_path, key)
        if row and row["last_compacted_at"] is not None:
            return row
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Session {key} was not compacted within {timeout}s")


@smoke
def test_nightly_compact_threshold_above_below(live_server):
    """Above-threshold session compacts; below-threshold session untouched.

    This is the critical end-to-end smoke: it proves _read_threshold() picks
    up settings.json AND nightly_compact() actually filters by it AND the
    below-threshold session is bit-for-bit unchanged after the run.
    """
    db_path = live_server["sessions_db"]

    # Seed: ABOVE has 5000 tokens, BELOW has 100 tokens. Threshold = 1000.
    _seed_session(db_path, SESSION_ABOVE, "smoke-orig-above-sid", token_count=5000)
    _seed_session(db_path, SESSION_BELOW, "smoke-orig-below-sid", token_count=100)

    above_before = _read_session(db_path, SESSION_ABOVE)
    below_before = _read_session(db_path, SESSION_BELOW)
    assert above_before is not None and above_before["last_compacted_at"] is None
    assert below_before is not None and below_before["last_compacted_at"] is None

    # Trigger nightly compact (localhost — server runs on 127.0.0.1)
    resp = httpx.post(f"{live_server['base_url']}/internal/nightly-compact/trigger", timeout=10)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Wait for the above-threshold session to be compacted
    above_after = _wait_for_compact(db_path, SESSION_ABOVE)

    # ABOVE: was compacted
    assert above_after["session_id"] != "smoke-orig-above-sid", \
        "above-threshold session should have a new session_id after /compact"
    assert above_after["last_compacted_at"] is not None
    assert above_after["last_compacted_at"] >= above_after["last_active"], \
        "last_compacted_at must be >= last_active to prevent re-compact loop"

    # BELOW: untouched (no waiting needed — should already be unchanged)
    below_after = _read_session(db_path, SESSION_BELOW)
    assert below_after["session_id"] == below_before["session_id"], \
        "below-threshold session_id must NOT change"
    assert below_after["last_compacted_at"] is None, \
        "below-threshold session must NOT be stamped"
    assert below_after["token_count"] == 100, \
        "below-threshold token_count must be unchanged"
    assert below_after["last_active"] == below_before["last_active"], \
        "below-threshold last_active must be unchanged"
