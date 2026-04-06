"""Unit tests for nightly compact eligibility + SessionStore methods."""
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
