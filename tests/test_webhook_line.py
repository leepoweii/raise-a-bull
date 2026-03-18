import pytest
from unittest.mock import AsyncMock, MagicMock
from raisebull.runner import RunResult


@pytest.mark.asyncio
async def test_handle_line_message_happy_path():
    """Normal message flow: runner succeeds, session saved."""
    mock_event = MagicMock()
    mock_event.source.user_id = "U_test"
    mock_event.reply_token = "rtoken"
    mock_event.message.text = "Hello"

    mock_sessions = AsyncMock()
    mock_sessions.get = AsyncMock(return_value=None)
    mock_sessions.save = AsyncMock()

    mock_runner = AsyncMock()
    mock_runner.run = AsyncMock(return_value=RunResult(text="Hi!", session_id="s1"))

    mock_api = MagicMock()

    from raisebull.webhook_line import handle_line_message
    await handle_line_message(mock_event, mock_runner, mock_sessions, mock_api)

    mock_runner.run.assert_awaited_once()
    mock_sessions.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_session_auto_recovery_on_line():
    """LINE handler auto-recovers from stale session_id transparently."""
    mock_event = MagicMock()
    mock_event.source.user_id = "U_stale"
    mock_event.reply_token = "rtoken"
    mock_event.message.text = "Hello"

    mock_sessions = AsyncMock()
    mock_sessions.get = AsyncMock(return_value={
        "session_id": "expired-id", "token_count": 50, "domain": "line"
    })
    mock_sessions.clear = AsyncMock()
    mock_sessions.save = AsyncMock()

    stale = RunResult(
        error="No conversation found with session ID: expired-id",
        stale_session=True,
    )
    fresh = RunResult(text="Hi!", session_id="new-id", input_tokens=10, output_tokens=5)

    mock_runner = AsyncMock()
    mock_runner.run = AsyncMock(side_effect=[stale, fresh])

    mock_api = MagicMock()

    from raisebull.webhook_line import handle_line_message
    await handle_line_message(mock_event, mock_runner, mock_sessions, mock_api)

    mock_sessions.clear.assert_awaited_once()
    assert mock_runner.run.await_count == 2
    # Session saved with new session_id
    saved_kwargs = mock_sessions.save.call_args.kwargs
    assert saved_kwargs["session_id"] == "new-id"
