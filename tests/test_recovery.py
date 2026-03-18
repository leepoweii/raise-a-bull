"""Integration tests for stale-session auto-recovery.

Uses a real fake-claude subprocess and a real SQLite session store.
No mocks — verifies the full recovery path end-to-end.
"""
from __future__ import annotations

import stat

import pytest
import pytest_asyncio

from raisebull.discord_bot import _run_with_recovery
from raisebull.runner import ClaudeRunner
from raisebull.session import SessionStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_claude(tmp_path):
    """Fake claude binary that mimics claude -p stream-json output.

    Behaviour:
    - --resume present  → exits 1 with "No conversation found" on stderr
    - no --resume       → emits valid stream-json and exits 0
    """
    script = tmp_path / "claude"
    script.write_text(
        "#!/bin/sh\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$arg\" = \"--resume\" ]; then\n"
        "    echo 'No conversation found with session ID: stale-id' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "done\n"
        "printf '{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"Hi!\"}]}}\\n'\n"
        "printf '{\"type\":\"result\",\"session_id\":\"new-sess\",\"cost_usd\":0.0,\"usage\":{\"input_tokens\":5,\"output_tokens\":3}}\\n'\n"
        "exit 0\n"
    )
    mode = script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    script.chmod(mode)
    return str(script)


@pytest_asyncio.fixture
async def store(tmp_path):
    s = SessionStore(str(tmp_path / "test.db"))
    await s.init()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_session_succeeds(fake_claude, store):
    """Fresh run with no session_id returns text and a new session_id."""
    runner = ClaudeRunner(claude_bin=fake_claude)

    result, effective_sid = await _run_with_recovery(
        runner, store, "discord:1", "Hello", None
    )

    assert result.text == "Hi!"
    assert effective_sid == "new-sess"
    assert result.error is None
    assert result.stale_session is False


@pytest.mark.asyncio
async def test_stale_session_auto_recovers(fake_claude, store):
    """Stale session: subprocess exits 1, recovery clears DB and retries fresh.

    Verifies end-to-end:
    1. Runner detects the real subprocess exit 1 + stderr
    2. stale_session=True is set on RunResult
    3. _run_with_recovery clears the session from real SQLite
    4. Retries without --resume → fresh subprocess call → valid response
    """
    runner = ClaudeRunner(claude_bin=fake_claude)

    # Seed a stale session into real SQLite
    await store.save("discord:1", session_id="stale-id", domain="general", token_count=100)
    row = await store.get("discord:1")
    assert row["session_id"] == "stale-id"

    # Run with recovery (real subprocess, real DB)
    result, effective_sid = await _run_with_recovery(
        runner, store, "discord:1", "Hello", "stale-id"
    )

    # Recovery succeeded — got a valid response
    assert result.text == "Hi!"
    assert effective_sid == "new-sess"
    assert result.error is None

    # Stale session was cleared from real SQLite
    # (handler is responsible for saving the new session_id after this returns)
    row_after = await store.get("discord:1")
    assert row_after is None


@pytest.mark.asyncio
async def test_non_stale_error_is_not_retried(fake_claude, store):
    """A subprocess failure that isn't a stale session is returned as-is, no retry."""
    # Script that always fails with a generic error
    import pathlib
    import stat as stat_mod
    bad_claude = pathlib.Path(str(fake_claude) + "_bad")
    bad_claude.write_text(
        "#!/bin/sh\necho 'Permission denied' >&2\nexit 1\n"
    )
    bad_claude.chmod(bad_claude.stat().st_mode | stat_mod.S_IEXEC)

    runner = ClaudeRunner(claude_bin=str(bad_claude))

    result, effective_sid = await _run_with_recovery(
        runner, store, "discord:1", "Hello", None
    )

    assert result.error is not None
    assert result.stale_session is False  # not a stale-session error
    assert result.text == ""
