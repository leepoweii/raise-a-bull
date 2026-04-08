"""Audit log coverage for scheduler entry points in heartbeat.py."""
import pytest

from raisebull.audit import AuditLog


@pytest.mark.asyncio
async def test_scheduler_heartbeat_recorded(monkeypatch, tmp_path):
    from raisebull.heartbeat import run_event_check

    al = AuditLog(":memory:")
    await al.init()

    # Stub out the actual work: runner.run and sessions access
    class _FakeRunner:
        workspace = str(tmp_path)

        async def run(self, *args, **kwargs):
            class _Result:
                session_id = None
                output = ""
                input_tokens = 0
                output_tokens = 0
                error = None
                stale_session = False
            return _Result()

    class _FakeSessions:
        async def get(self, key):
            return None

        async def save(self, *args, **kwargs):
            return None

    # Create an empty heartbeat.md so the function has nothing to do
    (tmp_path / "heartbeat").mkdir(exist_ok=True)
    (tmp_path / "heartbeat" / "heartbeat.md").write_text("# Empty\n")
    monkeypatch.setenv("WORKSPACE", str(tmp_path))

    # The audit call is at the top of _heartbeat_tick (before any file I/O
    # or runner logic). Wrap in try/except so the test only asserts the
    # audit row was written, even if downstream _heartbeat_tick logic
    # raises on the stub fixtures.
    try:
        await run_event_check(
            _FakeRunner(),
            _FakeSessions(),
            push_fn=None,
            audit_log=al,
        )
    except Exception:
        pass

    rows = await al.list_recent(limit=10)
    assert len(rows) >= 1
    assert any(
        r["action"] == "scheduler.heartbeat" and r["actor"] == "scheduler"
        for r in rows
    )
    await al.close()


@pytest.mark.asyncio
async def test_scheduler_nightly_compact_recorded(monkeypatch, tmp_path):
    from raisebull.heartbeat import nightly_compact

    al = AuditLog(":memory:")
    await al.init()

    class _FakeRunner:
        workspace = str(tmp_path)

        async def run(self, *args, **kwargs):
            class _Result:
                session_id = None
                output = ""
                input_tokens = 0
                output_tokens = 0
                error = None
                stale_session = False
            return _Result()

    class _FakeSessions:
        async def list_all(self):
            return []  # no eligible sessions

        async def get(self, key):
            return None

    try:
        await nightly_compact(
            _FakeRunner(),
            _FakeSessions(),
            buffer=None,
            audit_log=al,
        )
    except Exception:
        pass

    rows = await al.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "scheduler.nightly_compact"
    assert rows[0]["actor"] == "scheduler"
    await al.close()


@pytest.mark.asyncio
async def test_scheduler_discord_push_records_truncated_message(monkeypatch, tmp_path):
    """The heartbeat_push callback records only the first 200 chars of content."""
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "x")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "x")
    monkeypatch.setenv("WORKSPACE", str(tmp_path))
    monkeypatch.setenv("CREDENTIALS_DB_PATH", str(tmp_path / "creds.db"))

    import sys
    # Remove cached main module so env vars take effect on re-import
    sys.modules.pop("raisebull.main", None)

    import raisebull.main as main

    al = AuditLog(":memory:")
    await al.init()
    monkeypatch.setattr(main, "_audit_log", al)

    # Build a fake bot with one guild + one text_channel
    class _FakeChannel:
        name = "daily-ops"
        sent: list[str] = []

        async def send(self, msg):
            self.sent.append(msg)

    class _FakeGuild:
        text_channels = [_FakeChannel()]

    class _FakeBot:
        guilds = [_FakeGuild()]

    monkeypatch.setattr(main, "get_bot", lambda: _FakeBot())

    # Re-create the push callback with the stubbed _audit_log visible
    # (the real one is closured in lifespan — we need to call it here)
    # For testability, the implementation uses the module-level _audit_log
    # so we can call it directly.
    import discord  # noqa: F401 — matches production import path

    long_message = "X" * 500

    # Call the push callback function directly. The implementation
    # is defined in main.py lifespan; we access it via main._heartbeat_push
    # after a minimal lifespan setup. Simpler: instantiate a standalone
    # function mirroring the one in lifespan, but since this test targets
    # the real callback, we call main.lifespan's internal helper by
    # extracting it via monkeypatch. For now, call the module-level
    # helper `_heartbeat_push_impl` we will add in Step 3.
    from raisebull.main import _heartbeat_push_impl
    await _heartbeat_push_impl("daily-ops", long_message)

    rows = await al.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "scheduler.discord_push"
    assert rows[0]["actor"] == "scheduler"
    assert rows[0]["target"] == "daily-ops"
    assert rows[0]["after_val"] == "X" * 200  # truncated to 200 chars
    await al.close()
