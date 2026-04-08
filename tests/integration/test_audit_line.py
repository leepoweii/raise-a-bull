"""Audit log coverage for LINE webhook signature failures."""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_line_signature_fail_recorded(monkeypatch, tmp_path):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "test-secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "sessions.db"))
    monkeypatch.setenv("WORKSPACE", str(tmp_path))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_PASSWORD", "test")

    import raisebull.main as main
    from raisebull.audit import AuditLog

    al = AuditLog(":memory:")
    await al.init()
    monkeypatch.setattr(main, "_audit_log", al)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Invalid signature — webhook parser will reject
        resp = await c.post(
            "/webhook/line",
            content=b'{"events": []}',
            headers={
                "X-Line-Signature": "invalid-signature-xyz",
                "content-type": "application/json",
            },
        )
        assert resp.status_code == 400

    rows = await al.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "line.signature_fail"
    assert rows[0]["actor"] == "unknown"
    await al.close()
