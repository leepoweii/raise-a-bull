import pytest
from raisebull.runner import RunResult, ClaudeRunner

def test_run_result_defaults():
    r = RunResult()
    assert r.text == ""
    assert r.session_id is None
    assert r.error is None

def test_build_cmd_no_session():
    runner = ClaudeRunner(workspace="/tmp/ws")
    cmd = runner._build_cmd("hello", None)
    assert "claude" in cmd[0]
    assert "-p" in cmd
    assert "hello" in cmd
    assert "--add-dir" in cmd
    assert "/tmp/ws" in cmd
    assert "--resume" not in cmd

def test_build_cmd_with_session():
    runner = ClaudeRunner(workspace="/tmp/ws")
    cmd = runner._build_cmd("hello", "sess123")
    assert "--resume" in cmd
    assert "sess123" in cmd


def test_stale_session_flag_on_run_result_defaults_false():
    r = RunResult()
    assert r.stale_session is False


def test_stale_session_detected_in_result():
    runner = ClaudeRunner()
    assert runner._is_stale_session_error("No conversation found with session ID: abc123") is True
    assert runner._is_stale_session_error("exit 1") is False
    assert runner._is_stale_session_error("") is False
    assert runner._is_stale_session_error(None) is False


def test_parse_lines_detects_is_error_stale_session():
    """_parse_lines sets stale_session=True when stdout contains is_error=true with 'No conversation found'."""
    runner = ClaudeRunner()
    # This is the exact stdout format Claude Code 2.1.78+ emits for stale sessions
    is_error_event = (
        b'{"type":"result","subtype":"error_during_execution","is_error":true,'
        b'"session_id":"new-id","errors":["No conversation found with session ID: old-id"],'
        b'"usage":{"input_tokens":0,"output_tokens":0},"cost_usd":0}'
    )
    result = runner._parse_lines([is_error_event])
    assert result.stale_session is True
    assert result.error == "No conversation found with session ID: old-id"
    assert result.text == ""


def test_parse_lines_is_error_not_stale_for_other_errors():
    """_parse_lines sets error but not stale_session for non-stale is_error events."""
    runner = ClaudeRunner()
    is_error_event = (
        b'{"type":"result","subtype":"error_during_execution","is_error":true,'
        b'"session_id":"sid","errors":["Some other error"],'
        b'"usage":{"input_tokens":0,"output_tokens":0},"cost_usd":0}'
    )
    result = runner._parse_lines([is_error_event])
    assert result.error == "Some other error"
    assert result.stale_session is False


@pytest.mark.asyncio
async def test_run_stdout_is_error_not_overwritten_by_returncode(tmp_path):
    """Regression: run() must not overwrite stale_session detected from stdout is_error.

    Claude 2.1.78+ emits stale-session errors as stdout JSON with is_error=true
    and exit code 1. The old code would overwrite result.error with stderr output,
    losing the stale_session=True flag and breaking auto-recovery.
    """
    import stat as stat_mod

    # Fake claude: emits is_error JSON to stdout AND junk to stderr, exits 1
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        "printf '{\"type\":\"result\",\"subtype\":\"error_during_execution\","
        "\"is_error\":true,\"session_id\":\"new-id\","
        "\"errors\":[\"No conversation found with session ID: old-id\"],"
        "\"usage\":{\"input_tokens\":0,\"output_tokens\":0},\"cost_usd\":0}\\n'\n"
        "echo 'some stderr noise' >&2\n"
        "exit 1\n"
    )
    fake.chmod(fake.stat().st_mode | stat_mod.S_IEXEC)

    runner = ClaudeRunner(claude_bin=str(fake))
    result = await runner.run("hello", session_id="old-id")

    # Must preserve the stdout-detected error, not replace with "some stderr noise"
    assert result.stale_session is True
    assert "No conversation found" in result.error
    assert result.text == ""


import json

def test_parse_lines_fires_trace_steps():
    """_parse_lines should still work; trace extraction is in the stream loop."""
    runner = ClaudeRunner()
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello!"}]},
        }).encode(),
        json.dumps({
            "type": "result",
            "session_id": "s1",
            "cost_usd": 0.01,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }).encode(),
    ]
    result = runner._parse_lines(lines)
    assert result.text == "Hello!"
    assert result.session_id == "s1"


@pytest.mark.asyncio
async def test_run_collects_trace_steps(tmp_path):
    """on_trace callback receives TraceStep objects from stream-json."""
    import stat as stat_mod
    from raisebull.trace import TraceStep

    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"Let me think..."}]}}\\n\'\n'
        'printf \'{"type":"assistant","message":{"content":[{"type":"tool_use","id":"c1","name":"Read","input":{"file_path":"/tmp/x"}}]}}\\n\'\n'
        'printf \'{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"c1","content":"file data"}]}}\\n\'\n'
        'printf \'{"type":"assistant","message":{"content":[{"type":"text","text":"Here is the answer."}]}}\\n\'\n'
        'printf \'{"type":"result","session_id":"s1","cost_usd":0.0,"usage":{"input_tokens":10,"output_tokens":5}}\\n\'\n'
        "exit 0\n"
    )
    fake.chmod(fake.stat().st_mode | stat_mod.S_IEXEC)

    runner = ClaudeRunner(claude_bin=str(fake))
    collected: list[TraceStep] = []

    async def on_trace(step: TraceStep):
        collected.append(step)

    result = await runner.run("test", on_trace=on_trace)

    assert result.text == "Here is the answer."
    assert result.session_id == "s1"
    assert len(collected) == 4
    assert collected[0].step_type == "thinking"
    assert collected[1].step_type == "tool_call"
    assert collected[1].content["name"] == "Read"
    assert collected[2].step_type == "tool_result"
    assert collected[3].step_type == "text"
