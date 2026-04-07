"""Unit tests for nightly compact eligibility + SessionStore methods."""
import asyncio
import pytest
import pytest_asyncio
from raisebull.heartbeat import is_compact_eligible
from raisebull.session import SessionStore


class TestCompactEligibility:
    def test_eligible_high_tokens_no_compact(self):
        session = {"token_count": 60000, "last_compacted_at": None, "last_active": "2026-04-07T10:00:00"}
        assert is_compact_eligible(session) is True

    def test_not_eligible_low_tokens(self):
        session = {"token_count": 30000, "last_compacted_at": None, "last_active": "2026-04-07T10:00:00"}
        assert is_compact_eligible(session) is False

    def test_not_eligible_recently_compacted_no_new_activity(self):
        session = {
            "token_count": 60000,
            "last_compacted_at": "2026-04-07T02:00:00",
            "last_active": "2026-04-06T10:00:00",  # BEFORE compact
        }
        assert is_compact_eligible(session) is False

    def test_eligible_new_activity_after_compact(self):
        session = {
            "token_count": 60000,
            "last_compacted_at": "2026-04-06T03:00:00",
            "last_active": "2026-04-07T10:00:00",  # AFTER compact
        }
        assert is_compact_eligible(session) is True

    def test_skip_heartbeat_sessions(self):
        session = {"token_count": 100000, "last_compacted_at": None, "last_active": "2026-04-07T10:00:00"}
        assert is_compact_eligible(session, key="heartbeat:system") is False

    def test_threshold_boundary(self):
        session = {"token_count": 50000, "last_compacted_at": None, "last_active": "2026-04-07T10:00:00"}
        assert is_compact_eligible(session) is False  # must be > 50K, not >=

    def test_eligible_with_custom_threshold_below_token_count(self):
        session = {
            "token_count": 3000,
            "last_compacted_at": None,
            "last_active": "2026-04-07T10:00:00",
        }
        assert is_compact_eligible(session, threshold=2000) is True

    def test_not_eligible_with_custom_threshold_above_token_count(self):
        session = {
            "token_count": 1500,
            "last_compacted_at": None,
            "last_active": "2026-04-07T10:00:00",
        }
        assert is_compact_eligible(session, threshold=2000) is False

    def test_custom_threshold_uses_strict_greater_than(self):
        session = {
            "token_count": 2000,
            "last_compacted_at": None,
            "last_active": "2026-04-07T10:00:00",
        }
        assert is_compact_eligible(session, threshold=2000) is False


class TestSessionStoreListAll:
    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_list_all_returns_all_sessions(self, store):
        await store.save("discord:1", session_id="s1", domain="discord", token_count=100)
        await store.save("line:2", session_id="s2", domain="line", token_count=200)
        result = await store.list_all()
        assert len(result) == 2
        keys = {r["key"] for r in result}
        assert keys == {"discord:1", "line:2"}

    @pytest.mark.asyncio
    async def test_list_all_empty(self, store):
        result = await store.list_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_all_includes_last_compacted_at(self, store):
        await store.save("discord:1", session_id="s1", domain="discord", token_count=100)
        result = await store.list_all()
        assert "last_compacted_at" in result[0]
        assert result[0]["last_compacted_at"] is None


class TestSessionStoreUpdateCompactedAt:
    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_update_compacted_at(self, store):
        await store.save("discord:1", session_id="s1", domain="discord", token_count=100)
        await store.update_compacted_at("discord:1", "2026-04-07T03:00:00")
        row = await store.get("discord:1")
        assert row["last_compacted_at"] == "2026-04-07T03:00:00"

    @pytest.mark.asyncio
    async def test_update_compacted_at_nonexistent_key(self, store):
        # Should not raise, just 0 rows affected
        await store.update_compacted_at("nonexistent", "2026-04-07T03:00:00")


class TestReadThreshold:
    def test_default_when_no_settings_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_env_overrides_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "12345")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 12345

    def test_settings_json_overrides_env(self, tmp_path, monkeypatch):
        import json
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "12345")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "9999"})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 9999

    def test_settings_int_value_works(self, tmp_path, monkeypatch):
        import json
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": 7777})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 7777

    def test_zero_in_settings_falls_back_to_default(self, tmp_path, monkeypatch):
        import json
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "0"})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_negative_in_settings_falls_back_to_default(self, tmp_path, monkeypatch):
        import json
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "-100"})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_garbage_in_settings_falls_back_to_env(self, tmp_path, monkeypatch):
        import json
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "8888")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "abc"})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 8888

    def test_garbage_env_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "not-a-number")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_zero_in_env_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "0")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_negative_in_env_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "-50")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 50000

    def test_corrupted_settings_json_falls_back_to_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "6666")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text("{ not valid json")
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 6666

    def test_missing_workspace_directory_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        nonexistent = tmp_path / "does-not-exist"
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(nonexistent)) == 50000


class TestNightlyCompactThreshold:
    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_nightly_compact_uses_threshold_from_settings(
        self, store, tmp_path, monkeypatch
    ):
        """nightly_compact reads threshold from workspace/config/settings.json."""
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        # Seed sessions: one above custom threshold (1000), one below
        await store.save("web:above", session_id="orig-above", domain="web", token_count=2000)
        await store.save("web:below", session_id="orig-below", domain="web", token_count=500)

        # Write settings.json with low threshold so "above" becomes eligible
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        # Mock runner: /compact returns a new session id, consolidate is no-op
        runner = MagicMock()
        runner.workspace = str(workspace)
        compact_result = MagicMock(error=None, session_id="new-above-sid", output_tokens=900)
        consolidate_result = MagicMock(error=None, session_id=None, output_tokens=10)
        runner.run = AsyncMock(side_effect=[compact_result, consolidate_result])

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)

        await nightly_compact(runner, store, buffer=None)

        # "above" was compacted: new session_id, token_count updated
        above = await store.get("web:above")
        assert above["session_id"] == "new-above-sid"
        assert above["last_compacted_at"] is not None

        # "below" untouched
        below = await store.get("web:below")
        assert below["session_id"] == "orig-below"
        assert below["last_compacted_at"] is None
        assert below["token_count"] == 500

        # runner.run called exactly twice: once for /compact, once for consolidate
        assert runner.run.call_count == 2
        first_call_prompt = runner.run.call_args_list[0].args[0]
        assert first_call_prompt == "/compact"

    @pytest.mark.asyncio
    async def test_concurrent_runs_serialize_via_lock(
        self, store, tmp_path, monkeypatch
    ):
        """Two concurrent nightly_compact calls must not double-compact a session.

        Without a lock: both runs see the session as eligible (token_count > threshold,
        last_compacted_at is None) and both call runner.run for /compact + consolidate
        → 4 runner.run calls total. With the lock: run 1 holds the lock, compacts the
        session, releases. Run 2 takes the lock, sees the session is no longer eligible
        (last_compacted_at is now set, last_active is unchanged), and exits early
        without calling runner.run → 2 total calls.
        """
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        await store.save("web:hot", session_id="orig", domain="web", token_count=5000)

        runner = MagicMock()
        runner.workspace = str(workspace)

        async def slow_run(*args, **kwargs):
            # Simulate a non-trivial Claude call so the two coroutines actually overlap
            # in time if they're not serialized.
            await asyncio.sleep(0.05)
            return MagicMock(error=None, session_id="new-sid", output_tokens=900)

        runner.run = AsyncMock(side_effect=slow_run)

        # Fire two concurrent nightly_compact runs
        await asyncio.gather(
            nightly_compact(runner, store, buffer=None),
            nightly_compact(runner, store, buffer=None),
        )

        # Run 1: 1× /compact + 1× consolidate = 2 runner.run calls.
        # Run 2: lock blocks until Run 1 finishes; then Run 2 sees the now-compacted
        # session as ineligible (last_compacted_at >= last_active) and exits before
        # calling runner.run at all.
        assert runner.run.call_count == 2, (
            f"Expected serialized execution (2 calls), got {runner.run.call_count}. "
            "Without the lock, both runs would each call /compact + consolidate = 4 calls."
        )

        # Sanity: the session was actually compacted exactly once
        row = await store.get("web:hot")
        assert row["session_id"] == "new-sid"
        assert row["last_compacted_at"] is not None


class TestNightlyCompactLogging:
    """Verifies nightly_compact emits the log lines operators rely on to debug
    threshold behavior. Phase 3 curl verification noted a partial pass on Check L:
    no log output was visible from the compact job, leaving operators blind to
    what threshold was actually in use at runtime. These tests pin the log
    contract so a future refactor can't silently drop the threshold value from
    the log lines.
    """

    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_logs_no_eligible_with_threshold_value(
        self, store, tmp_path, monkeypatch, caplog
    ):
        """Empty-session run must log 'no eligible sessions (threshold=<N>)'
        so operators can see what threshold was in effect on an idle night."""
        import logging
        from unittest.mock import MagicMock
        from raisebull.heartbeat import nightly_compact

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "4242"}'
        )

        runner = MagicMock()
        runner.workspace = str(workspace)

        with caplog.at_level(logging.INFO, logger="raisebull.heartbeat"):
            await nightly_compact(runner, store, buffer=None)

        # The "no eligible" log MUST include the threshold value so an operator
        # can confirm the dashboard-configured threshold actually took effect.
        assert "no eligible sessions" in caplog.text
        assert "threshold=4242" in caplog.text

    @pytest.mark.asyncio
    async def test_logs_per_session_tokens_and_threshold(
        self, store, tmp_path, monkeypatch, caplog
    ):
        """For each eligible session, the log line must include BOTH the token
        count AND the threshold so operators can see which sessions qualified
        and by how much."""
        import logging
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        await store.save("web:hot", session_id="orig", domain="web", token_count=3500)

        runner = MagicMock()
        runner.workspace = str(workspace)
        compact_result = MagicMock(error=None, session_id="new-sid", output_tokens=800)
        consolidate_result = MagicMock(error=None, session_id=None, output_tokens=10)
        runner.run = AsyncMock(side_effect=[compact_result, consolidate_result])

        with caplog.at_level(logging.INFO, logger="raisebull.heartbeat"):
            await nightly_compact(runner, store, buffer=None)

        # Per-session line format: "Nightly compact: <key> (tokens=<N>, threshold=<M>)"
        assert "Nightly compact: web:hot" in caplog.text
        assert "tokens=3500" in caplog.text
        assert "threshold=1000" in caplog.text
        # Consolidate completion log must also appear so operators know the run finished
        assert "Nightly consolidate complete" in caplog.text
