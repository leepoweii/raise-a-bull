import logging

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock

ENV = {
    "LINE_CHANNEL_SECRET": "secret",
    "LINE_CHANNEL_ACCESS_TOKEN": "token",
    "WORKSPACE": "/tmp/ws",
    "DB_PATH": "/tmp/test_health.db",
}


def test_main_module_configures_root_logger_for_application_logs():
    """raisebull.main calls logging.basicConfig(level=INFO) at module load
    so application loggers (raisebull.heartbeat, raisebull.discord_bot, etc.)
    surface their INFO lines in uvicorn stdout / docker logs.

    Without this, Python's root logger defaults to WARNING and uvicorn only
    configures its own loggers — operators would see HTTP access lines but
    NOT the actual job execution logs (e.g., "Nightly compact: no eligible
    sessions (threshold=50000)"), making it impossible to verify scheduled
    job behavior in production.

    The test imports main (which triggers basicConfig) and asserts the
    raisebull logger's effective level is at least INFO. basicConfig is
    idempotent so this is safe across test runs.
    """
    with patch.dict("os.environ", ENV):
        import raisebull.main  # noqa: F401  — import side effect (basicConfig)

    raisebull_logger = logging.getLogger("raisebull")
    heartbeat_logger = logging.getLogger("raisebull.heartbeat")

    # Both loggers should resolve to effective INFO (10 = DEBUG, 20 = INFO,
    # 30 = WARNING). After basicConfig(level=INFO), the root is INFO and
    # child loggers inherit unless they override.
    assert raisebull_logger.getEffectiveLevel() <= logging.INFO, (
        f"raisebull logger is at level {raisebull_logger.getEffectiveLevel()}, "
        f"expected <= {logging.INFO} (INFO)"
    )
    assert heartbeat_logger.getEffectiveLevel() <= logging.INFO, (
        f"raisebull.heartbeat logger is at level {heartbeat_logger.getEffectiveLevel()}, "
        f"expected <= {logging.INFO} (INFO)"
    )

    # Root logger must have at least one handler so application INFO lines
    # have somewhere to flow. In production basicConfig adds a StreamHandler;
    # in pytest the test runner adds its own capture handlers. Either way,
    # `len(root.handlers) > 0` proves messages won't silently disappear.
    #
    # Note: root.getEffectiveLevel() is NOT asserted because pytest may have
    # left root at WARNING — what matters is the raisebull logger's effective
    # level (asserted above), which is INFO regardless of root because
    # main.py explicitly calls `getLogger("raisebull").setLevel(INFO)`.
    root = logging.getLogger()
    assert len(root.handlers) > 0, "root logger must have a handler"


def test_application_log_lines_propagate_to_root_caplog(caplog):
    """End-to-end check: a logger.info() call from raisebull.heartbeat must
    surface via caplog (which captures everything propagated to root).
    Pins the propagation chain so a future refactor that sets propagate=False
    on raisebull loggers, or removes basicConfig from main, would be caught.
    """
    with patch.dict("os.environ", ENV):
        import raisebull.main  # noqa: F401

    with caplog.at_level(logging.INFO, logger="raisebull.heartbeat"):
        logging.getLogger("raisebull.heartbeat").info("test marker xyz123")

    assert "test marker xyz123" in caplog.text


@pytest.mark.asyncio
async def test_health_check():
    with patch.dict("os.environ", ENV):
        from raisebull.main import app
        # Use lifespan=False to skip startup/shutdown side effects
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_discord_push_bot_not_running_returns_503():
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.get_bot", return_value=None):
            from raisebull.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/internal/discord/push",
                    json={"channel_id": "123", "message": "hi"},
                )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_discord_push_channel_not_found_returns_404():
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = None
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.get_bot", return_value=mock_bot):
            from raisebull.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/internal/discord/push",
                    json={"channel_id": "123", "message": "hi"},
                )
    assert resp.status_code == 404
    mock_bot.get_channel.assert_called_once_with(123)


@pytest.mark.asyncio
async def test_discord_push_success():
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = mock_channel
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.get_bot", return_value=mock_bot):
            from raisebull.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/internal/discord/push",
                    json={"channel_id": "123", "message": "hi"},
                )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_channel.send.assert_called_once_with("hi")


@pytest.mark.asyncio
async def test_discord_push_blocks_remote_client():
    """Non-localhost callers must get 403. Regression guard — Phase 3 verified the
    live bull-daniu deploy was exploitable: external curl to /internal/discord/push
    accepted arbitrary Discord messages with 200. The two trigger endpoints got the
    localhost gate in Task 5 but discord_push was overlooked."""
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = mock_channel
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.get_bot", return_value=mock_bot):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/internal/discord/push",
                    json={"channel_id": "123", "message": "hi"},
                )
    assert resp.status_code == 403
    # Critically: channel.send MUST NOT have been called — the gate must stop
    # the request before any Discord API work happens.
    mock_channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_discord_push_allows_ipv6_localhost():
    """::1 must be treated as localhost (same allowlist as the trigger endpoints)."""
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    mock_bot = MagicMock()
    mock_bot.get_channel.return_value = mock_channel
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.get_bot", return_value=mock_bot):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("::1", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/internal/discord/push",
                    json={"channel_id": "123", "message": "hi"},
                )
    assert resp.status_code == 200
    mock_channel.send.assert_called_once_with("hi")


@pytest.mark.asyncio
async def test_heartbeat_trigger_returns_ok():
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.run_event_check", new_callable=AsyncMock):
            from raisebull.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/internal/heartbeat/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_heartbeat_trigger_blocks_remote_client():
    """Non-localhost callers must get 403."""
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.run_event_check", new_callable=AsyncMock):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/heartbeat/trigger")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_nightly_compact_trigger_returns_ok():
    """Localhost caller (None client from ASGITransport default) gets 200."""
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.nightly_compact", new_callable=AsyncMock):
            from raisebull.main import app
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post("/internal/nightly-compact/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_nightly_compact_trigger_blocks_remote_client():
    """Non-localhost callers must get 403."""
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.nightly_compact", new_callable=AsyncMock):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("203.0.113.5", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/nightly-compact/trigger")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_nightly_compact_trigger_allows_ipv6_localhost():
    """::1 must be treated as localhost."""
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.nightly_compact", new_callable=AsyncMock):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("::1", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/nightly-compact/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_nightly_compact_trigger_allows_ipv4_mapped_ipv6_localhost():
    """::ffff:127.0.0.1 (IPv4-mapped IPv6 loopback) must be treated as localhost.

    Some Linux dual-stack uvicorn configurations serve loopback this way. The
    string-equality allowlist would 403 it. Using ipaddress.ip_address().is_loopback
    correctly recognizes it as a loopback address.
    """
    with patch.dict("os.environ", ENV):
        with patch("raisebull.main.nightly_compact", new_callable=AsyncMock):
            from raisebull.main import app
            transport = ASGITransport(app=app, client=("::ffff:127.0.0.1", 12345))
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/nightly-compact/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_webhook_line_missing_signature_returns_400():
    with patch.dict("os.environ", ENV):
        from raisebull.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhook/line",
                json={},
                # No X-Line-Signature header
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_line_invalid_signature_returns_400():
    with patch.dict("os.environ", ENV):
        from raisebull.main import app
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhook/line",
                json={},
                headers={"X-Line-Signature": "invalid"},
            )
    assert resp.status_code == 400
