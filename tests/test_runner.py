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
