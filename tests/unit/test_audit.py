"""Unit tests for AuditLog class."""
import pytest
import pytest_asyncio

from raisebull.audit import AuditLog


@pytest_asyncio.fixture
async def audit():
    al = AuditLog(":memory:")
    await al.init()
    yield al
    await al.close()


class TestAuditLog:
    @pytest.mark.asyncio
    async def test_init_creates_table(self, audit):
        # Insert + select with raw SQL proves table + indexes exist
        db = audit._require_db()
        await db.execute(
            "INSERT INTO audit_log (ts, actor, action) VALUES (?, ?, ?)",
            ("2026-04-08T00:00:00+00:00", "admin", "test.action"),
        )
        await db.commit()
        async with db.execute("SELECT COUNT(*) FROM audit_log") as cur:
            row = await cur.fetchone()
            assert row[0] == 1

    @pytest.mark.asyncio
    async def test_record_round_trip(self, audit):
        await audit.record(
            "settings.put",
            actor="admin",
            target="nightly_compact_threshold",
            before_val="50000",
            after_val="9999",
            source_ip="192.168.1.5",
        )
        rows = await audit.list_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["actor"] == "admin"
        assert row["action"] == "settings.put"
        assert row["target"] == "nightly_compact_threshold"
        assert row["before_val"] == "50000"
        assert row["after_val"] == "9999"
        assert row["source_ip"] == "192.168.1.5"
        assert row["ts"].endswith("+00:00")  # UTC isoformat

    @pytest.mark.asyncio
    async def test_record_with_all_nulls(self, audit):
        await audit.record("scheduler.heartbeat", actor="scheduler")
        rows = await audit.list_recent(limit=10)
        assert len(rows) == 1
        row = rows[0]
        assert row["target"] is None
        assert row["before_val"] is None
        assert row["after_val"] is None
        assert row["source_ip"] is None

    @pytest.mark.asyncio
    async def test_list_recent_ordered_desc(self, audit):
        await audit.record("login.success", actor="admin")
        await audit.record("settings.put", actor="admin", target="model")
        await audit.record("session.delete", actor="admin", target="web:abc")
        rows = await audit.list_recent(limit=10)
        assert [r["action"] for r in rows] == [
            "session.delete", "settings.put", "login.success"
        ]

    @pytest.mark.asyncio
    async def test_list_recent_date_range_filter(self, audit):
        # Insert rows at specific timestamps using raw SQL
        db = audit._require_db()
        for ts in [
            "2026-04-01T00:00:00+00:00",
            "2026-04-05T12:00:00+00:00",
            "2026-04-10T23:59:59+00:00",
        ]:
            await db.execute(
                "INSERT INTO audit_log (ts, actor, action) VALUES (?, ?, ?)",
                (ts, "system", "scheduler.heartbeat"),
            )
        await db.commit()

        rows = await audit.list_recent(
            from_ts="2026-04-04T00:00:00+00:00",
            to_ts="2026-04-07T00:00:00+00:00",
            limit=10,
        )
        assert len(rows) == 1
        assert rows[0]["ts"] == "2026-04-05T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_list_recent_limit(self, audit):
        for i in range(10):
            await audit.record("scheduler.heartbeat", actor="scheduler")
        rows = await audit.list_recent(limit=5)
        assert len(rows) == 5
