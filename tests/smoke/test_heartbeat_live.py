"""Smoke test: heartbeat scheduler with real MiniMax M2.7.

Tests the full heartbeat loop:
1. Server starts with HEARTBEAT_INTERVAL=20s
2. Wait for tick 1 — session created, heartbeat_last set, last-run.json updated
3. Modify heartbeat.md via API
4. Wait for tick 2 — heartbeat_last changes, modified heartbeat picked up

Run with:
    ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic \
    ANTHROPIC_AUTH_TOKEN=<key> \
    uv run pytest tests/smoke/test_heartbeat_live.py -v -s
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

smoke = pytest.mark.skipif(
    not (os.environ.get("ANTHROPIC_BASE_URL") and os.environ.get("ANTHROPIC_AUTH_TOKEN")),
    reason="Requires ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN env vars",
)

HEARTBEAT_INTERVAL = 20  # seconds between ticks
MAX_WAIT_PER_TICK = 120  # max seconds to wait for a single tick
POLL_INTERVAL = 3  # seconds between status checks
PORT = 18799
PASSWORD = "smoke_heartbeat_test"


def _find_free_port():
    import socket
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Start a real uvicorn server with heartbeat enabled."""
    tmp = tmp_path_factory.mktemp("heartbeat_smoke")
    workspace = tmp / "workspace"
    workspace.mkdir()
    for d in ("config", "context", "skills", "heartbeat"):
        (workspace / d).mkdir()

    # Write initial heartbeat.md
    (workspace / "heartbeat" / "heartbeat.md").write_text(
        "## Smoke Test\n\n### 煙霧測試（每分鐘）\n- 回報時間\n- 發送到 [#management]\n"
    )
    (workspace / "heartbeat" / "last-run.json").write_text("{}")

    port = _find_free_port()
    sessions_db = str(tmp / "sessions.db")
    creds_db = str(tmp / "credentials.db")

    env = {
        **os.environ,
        "LINE_CHANNEL_SECRET": "dummy",
        "LINE_CHANNEL_ACCESS_TOKEN": "dummy",
        "DISCORD_BOT_TOKEN": "",
        "HEARTBEAT_INTERVAL": str(HEARTBEAT_INTERVAL),
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

    # Wait for server to start
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

    # Login
    client = httpx.Client(base_url=base_url, timeout=10)
    resp = client.post("/admin/api/auth", json={"password": PASSWORD})
    assert resp.status_code == 200

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


def _get_status(client):
    resp = client.get("/admin/api/status")
    assert resp.status_code == 200
    return resp.json()


def _wait_for_heartbeat(client, previous_value, label="tick"):
    """Poll status until heartbeat_last changes from previous_value."""
    start = time.time()
    while time.time() - start < MAX_WAIT_PER_TICK:
        status = _get_status(client)
        current = status.get("heartbeat_last")
        if current is not None and current != previous_value:
            return current, status
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Heartbeat {label} did not complete in {MAX_WAIT_PER_TICK}s")


@smoke
def test_heartbeat_full_lifecycle(live_server):
    """Full heartbeat smoke test: 2 ticks + heartbeat.md modification."""
    client = live_server["client"]
    workspace = live_server["workspace"]

    # --- Initial state ---
    status = _get_status(client)
    assert status["heartbeat_last"] is None
    assert status["sessions"]["heartbeat"] == 0

    # --- Tick 1: wait for first heartbeat ---
    tick1_time, status1 = _wait_for_heartbeat(client, None, "tick 1")
    assert isinstance(tick1_time, float)
    assert status1["sessions"]["heartbeat"] == 1  # session created

    # Verify last-run.json was updated by the agent
    last_run = json.loads((workspace / "heartbeat" / "last-run.json").read_text())
    assert last_run != {}  # agent wrote something

    # --- Modify heartbeat.md via API ---
    new_content = "## Modified\n\n### 新任務（每分鐘）\n- 說 MODIFIED\n- 發送到 [#management]\n"
    resp = client.put("/admin/api/heartbeat", json={"content": new_content})
    assert resp.status_code == 200

    # Verify API roundtrip
    resp = client.get("/admin/api/heartbeat")
    assert resp.json()["raw_markdown"] == new_content

    # --- Tick 2: wait for second heartbeat (should pick up modified heartbeat.md) ---
    tick2_time, status2 = _wait_for_heartbeat(client, tick1_time, "tick 2")
    assert tick2_time > tick1_time  # time advanced
    assert status2["sessions"]["heartbeat"] == 1  # same session, resumed

    # Verify last-run.json was updated again
    last_run2 = json.loads((workspace / "heartbeat" / "last-run.json").read_text())
    assert last_run2 != last_run  # agent updated it

    # --- Status endpoint reflects live state ---
    final_status = _get_status(client)
    assert final_status["heartbeat_last"] == tick2_time
    assert final_status["model"] == os.environ.get("ANTHROPIC_MODEL", "MiniMax-M2.7")
