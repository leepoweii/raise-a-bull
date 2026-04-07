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

    def test_whitespace_around_value_is_stripped(self, tmp_path, monkeypatch):
        """`_coerce_threshold("  42  ")` (leading/trailing whitespace) → 42.
        Pins the .strip() behavior so a future refactor that drops it would
        silently start rejecting otherwise-valid env values."""
        import json
        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": "  42  "})
        )
        from raisebull.heartbeat import _read_threshold
        assert _read_threshold(str(tmp_path)) == 42

    def test_nested_object_value_falls_through(self, tmp_path, monkeypatch):
        """`_coerce_threshold({"value": 42})` → None (falls through). Pins the
        defensive behavior when settings.json is malformed (e.g., a user
        accidentally writes `{"nightly_compact_threshold": {"value": 42}}`
        instead of `{"nightly_compact_threshold": 42}`). The function must
        NOT crash and must NOT treat the dict as valid."""
        import json
        monkeypatch.setenv("NIGHTLY_COMPACT_THRESHOLD", "8888")
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(
            json.dumps({"nightly_compact_threshold": {"value": 42}})
        )
        from raisebull.heartbeat import _read_threshold
        # Settings.json value is invalid → falls through to env (8888)
        assert _read_threshold(str(tmp_path)) == 8888


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

    @pytest.mark.asyncio
    async def test_compact_with_none_output_tokens_preserves_token_count(
        self, store, tmp_path, monkeypatch
    ):
        """If runner.run('/compact') returns result.output_tokens = None (which
        the runner can do if Claude doesn't report token usage), nightly_compact
        must NOT overwrite the row's token_count with None — it must fall back
        to the original token_count. Pins the `result.output_tokens or s["token_count"]`
        fallback behavior in heartbeat.py.

        IMPORTANT: the test MUST write a settings.json with a low threshold
        (1000) so the 5000-token seeded session IS eligible. Without this, the
        default 50000 threshold would skip the session entirely — runner.run
        would never be called, and the test would falsely "pass" by never
        exercising the fallback path at all.
        """
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        # Low threshold so the 5000-token session qualifies
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        await store.save("web:hot", session_id="orig", domain="web", token_count=5000)

        runner = MagicMock()
        runner.workspace = str(workspace)
        # /compact returns success but with output_tokens=None
        compact_result = MagicMock(error=None, session_id="new-sid", output_tokens=None)
        consolidate_result = MagicMock(error=None, session_id=None, output_tokens=None)
        runner.run = AsyncMock(side_effect=[compact_result, consolidate_result])

        await nightly_compact(runner, store, buffer=None)

        # Sanity: runner.run was actually called — proves the session WAS eligible
        # and the code reached the fallback path (not skipped by is_compact_eligible)
        assert runner.run.call_count == 2  # 1 /compact + 1 consolidate

        row = await store.get("web:hot")
        assert row["session_id"] == "new-sid"  # session was compacted
        # token_count must be the original 5000, NOT None — the fallback path
        # `result.output_tokens or s["token_count"]` evaluates to s["token_count"]
        # because None is falsy.
        assert row["token_count"] == 5000
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


class TestSessionStoreSaveWithCompactedAt:
    """Verifies that SessionStore.save_with_compacted_at writes both session_id
    and last_compacted_at in a single atomic statement, eliminating the
    crash-recovery race where a SIGTERM between save() and update_compacted_at()
    leaves the session with a fresh session_id but no compaction stamp.
    """

    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_updates_session_id_and_compacted_at_preserves_last_active(self, store):
        """The atomic UPDATE rotates session_id + token_count + domain + sets
        last_compacted_at, but DOES NOT touch last_active. last_active is the
        user-facing 'last real activity' timestamp displayed in
        discord_bot.py:434, webhook_line.py:144, and used as created_at in
        routes_chat.py:154 — touching it during a background compact would
        shift those displays to the cron's 03:00 AM run time."""
        # Pre-save creates the row with last_active = datetime.now() at save time
        await store.save("web:test", session_id="orig-sid", domain="web", token_count=5000)
        before = await store.get("web:test")
        original_last_active = before["last_active"]
        assert before["last_compacted_at"] is None  # baseline: not yet compacted

        # Compact runs — atomic UPDATE of session_id + last_compacted_at
        await store.save_with_compacted_at(
            "web:test",
            session_id="post-compact-sid",
            domain="web",
            token_count=900,
            compacted_at="2026-04-08T03:00:00+00:00",
        )

        row = await store.get("web:test")
        assert row["session_id"] == "post-compact-sid"   # rotated
        assert row["token_count"] == 900                 # updated
        assert row["domain"] == "web"
        assert row["last_compacted_at"] == "2026-04-08T03:00:00+00:00"
        # CRITICAL: last_active is UNCHANGED — preserves user-display semantics
        assert row["last_active"] == original_last_active

    @pytest.mark.asyncio
    async def test_invariant_compacted_at_strictly_after_last_active(self, store):
        """The re-compact-loop fix from d0b8642: is_compact_eligible() at
        heartbeat.py:50 returns False when `session["last_active"] <= last_compacted`
        (no new user activity since the compact). With UPDATE-based save, the
        invariant holds STRICTLY (compacted_at > last_active) because:
          - last_active is set by save() at time T1 (real user activity)
          - compacted_at is captured at time T2 > T1 (compact happened later)
          - The compact lock prevents user activity from racing the compact
        """
        # Save a row at the wall-clock "now"
        await store.save("web:test", session_id="sid", domain="web", token_count=5000)

        # Compact at a strictly later time (use a year-2099 timestamp to make
        # the inequality unambiguous regardless of test machine clock skew)
        compacted_at = "2099-12-31T23:59:59+00:00"
        await store.save_with_compacted_at(
            "web:test",
            session_id="new-sid",
            domain="web",
            token_count=900,
            compacted_at=compacted_at,
        )

        row = await store.get("web:test")
        # Strict inequality: compaction happened AFTER the user's last activity
        assert row["last_compacted_at"] > row["last_active"], (
            f"compacted_at={row['last_compacted_at']!r} should be strictly > "
            f"last_active={row['last_active']!r}"
        )
        # And the actual eligibility check from heartbeat.py:50 uses <=,
        # which trivially holds when strict > does
        assert row["last_active"] <= row["last_compacted_at"]

    @pytest.mark.asyncio
    async def test_replaces_session_id_atomically(self, store):
        """The new method must atomically rotate BOTH session_id AND
        last_compacted_at. A future refactor that splits them back into two
        statements (the v1 race) would re-introduce the crash-recovery loop.
        Asserts the post-state has both fields updated together.
        """
        await store.save("web:test", session_id="orig", domain="web", token_count=5000)
        await store.save_with_compacted_at(
            "web:test",
            session_id="post-compact",
            domain="web",
            token_count=800,
            compacted_at="2026-04-08T03:00:00+00:00",
        )
        row = await store.get("web:test")
        assert row["session_id"] == "post-compact"
        assert row["last_compacted_at"] == "2026-04-08T03:00:00+00:00"
        assert row["token_count"] == 800
        assert row["domain"] == "web"

    @pytest.mark.asyncio
    async def test_raises_keyerror_on_missing_key(self, store):
        """UPDATE on a non-existent row matches zero rows. The method must
        raise KeyError so the caller (nightly_compact) can log + skip when a
        session was deleted between is_compact_eligible() and the post-compact
        DB write (rare race with session.clear() or admin DELETE).
        """
        with pytest.raises(KeyError, match="web:nonexistent"):
            await store.save_with_compacted_at(
                "web:nonexistent",
                session_id="sid",
                domain="web",
                token_count=100,
                compacted_at="2026-04-08T03:00:00+00:00",
            )


class TestNightlyCompactKeyErrorHandling:
    """Verifies nightly_compact catches the KeyError raised by
    save_with_compacted_at and continues to the next eligible session
    instead of crashing the entire loop. Pins the try/except wiring in
    heartbeat.py so a future indentation slip can't silently break it.
    """

    @pytest_asyncio.fixture
    async def store(self, tmp_path):
        s = SessionStore(str(tmp_path / "test.db"))
        await s.init()
        yield s
        await s.close()

    @pytest.mark.asyncio
    async def test_nightly_compact_skips_session_deleted_mid_compact(
        self, store, tmp_path, monkeypatch
    ):
        """Two eligible sessions; the first one's save_with_compacted_at
        raises KeyError (simulating deletion mid-compact). nightly_compact
        must catch the error, log a warning, and continue to compact the
        second session. The whole loop must NOT crash.
        """
        from unittest.mock import AsyncMock, MagicMock
        from raisebull.heartbeat import nightly_compact

        monkeypatch.delenv("NIGHTLY_COMPACT_THRESHOLD", raising=False)
        workspace = tmp_path / "workspace"
        (workspace / "config").mkdir(parents=True)
        (workspace / "config" / "settings.json").write_text(
            '{"nightly_compact_threshold": "1000"}'
        )

        # Seed two eligible sessions
        await store.save("web:deleted", session_id="orig-deleted", domain="web", token_count=5000)
        await store.save("web:survives", session_id="orig-survives", domain="web", token_count=5000)

        # Wrap the real save_with_compacted_at — raise KeyError for the
        # "deleted" key, fall through to the real impl for everything else
        real_save = store.save_with_compacted_at
        save_calls: list[str] = []

        async def raising_save(key, **kwargs):
            save_calls.append(key)
            if key == "web:deleted":
                raise KeyError(f"No session for key {key!r}")
            return await real_save(key, **kwargs)

        store.save_with_compacted_at = raising_save  # type: ignore[method-assign]

        runner = MagicMock()
        runner.workspace = str(workspace)
        # Two /compact calls (one per eligible session) + 1 consolidate = 3 runner.run calls
        compact_a = MagicMock(error=None, session_id="new-a", output_tokens=900)
        compact_b = MagicMock(error=None, session_id="new-b", output_tokens=850)
        consolidate = MagicMock(error=None, session_id=None, output_tokens=10)
        runner.run = AsyncMock(side_effect=[compact_a, compact_b, consolidate])

        # MUST NOT raise — the KeyError on web:deleted must be caught + logged
        await nightly_compact(runner, store, buffer=None)

        # Both keys were attempted (proves the loop didn't bail early)
        assert "web:deleted" in save_calls
        assert "web:survives" in save_calls

        # The surviving session was actually compacted
        survives = await store.get("web:survives")
        assert survives["session_id"] == "new-b" or survives["session_id"] == "new-a", (
            "web:survives should have a rotated session_id (whichever order the loop ran)"
        )
        assert survives["last_compacted_at"] is not None

        # All 3 runner.run calls happened: 2 /compact + 1 consolidate
        assert runner.run.call_count == 3
