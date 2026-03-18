from raisebull.discord_bot import extract_domain_from_channel, _split_message

def test_extract_domain_unknown_channel():
    assert extract_domain_from_channel("some-random-channel") == "general"

def test_extract_domain_known_mapping():
    assert extract_domain_from_channel("morning") == "daily"

def test_project_channel_no_longer_special():
    # Samantha's _PROJECT_CHANNELS are gone — unknown channels → "general"
    assert extract_domain_from_channel("夢酒館") == "general"

def test_split_message_short():
    chunks = _split_message("hello")
    assert chunks == ["hello"]

def test_split_message_long():
    text = "x" * 4000
    chunks = _split_message(text)
    assert all(len(c) <= 1900 for c in chunks)
    assert "".join(chunks) == text


import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from raisebull.runner import RunResult


@pytest.mark.asyncio
async def test_stale_session_triggers_retry():
    """_run_with_recovery clears session and retries when stale_session=True."""
    from raisebull.discord_bot import _run_with_recovery

    key = "discord:123"
    prompt = "Hello"

    mock_sessions = AsyncMock()
    mock_sessions.clear = AsyncMock()

    stale_result = RunResult(
        error="No conversation found with session ID: old-id",
        stale_session=True,
    )
    fresh_result = RunResult(text="Hi!", session_id="new-id", input_tokens=10, output_tokens=5)

    mock_runner = AsyncMock()
    mock_runner.run = AsyncMock(side_effect=[stale_result, fresh_result])

    result, effective_sid = await _run_with_recovery(mock_runner, mock_sessions, key, prompt, "old-id")

    assert result.text == "Hi!"
    assert effective_sid == "new-id"
    mock_sessions.clear.assert_awaited_once_with(key)
    assert mock_runner.run.await_count == 2
    # Second call must pass session_id=None
    _, second_kwargs = mock_runner.run.call_args_list[1]
    assert second_kwargs.get("session_id") is None
