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
