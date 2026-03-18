import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_health_check():
    with patch.dict("os.environ", {
        "LINE_CHANNEL_SECRET": "secret",
        "LINE_CHANNEL_ACCESS_TOKEN": "token",
        "WORKSPACE": "/tmp/ws",
        "DB_PATH": "/tmp/test_health.db",
    }):
        from raisebull.main import app
        # Use lifespan=False to skip startup/shutdown side effects
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["version"] == "0.1.0"
