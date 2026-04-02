"""Unit tests for heartbeat prompt building and channel message parsing."""
import json
import pytest
from raisebull.heartbeat import build_heartbeat_prompt, parse_channel_messages


class TestBuildHeartbeatPrompt:
    def test_contains_current_time(self):
        prompt = build_heartbeat_prompt(
            now="2026-04-03 10:00:00", day="Thursday", time_str="10:00",
            last_run="2026-04-03 09:00:00",
            heartbeat_path="/app/workspace/heartbeat/heartbeat.md",
            lastrun_path="/app/workspace/heartbeat/last-run.json",
        )
        assert "2026-04-03 10:00:00" in prompt
        assert "Thursday" in prompt
        assert "heartbeat.md" in prompt

    def test_contains_paths(self):
        prompt = build_heartbeat_prompt(
            now="2026-04-03 10:00:00", day="Thursday", time_str="10:00",
            last_run="never",
            heartbeat_path="/app/workspace/heartbeat/heartbeat.md",
            lastrun_path="/app/workspace/heartbeat/last-run.json",
        )
        assert "/app/workspace/heartbeat/heartbeat.md" in prompt
        assert "/app/workspace/heartbeat/last-run.json" in prompt


class TestParseChannelMessages:
    def test_single_channel_message(self):
        text = "[#management] 今日庫存正常，無需補貨。"
        result = parse_channel_messages(text)
        assert len(result) == 1
        assert result[0] == ("management", "今日庫存正常，無需補貨。")

    def test_multiple_channel_messages(self):
        text = "[#management] 早安報告\n[#shipping] 今天有 3 筆出貨"
        result = parse_channel_messages(text)
        assert len(result) == 2
        assert result[0][0] == "management"
        assert result[1][0] == "shipping"

    def test_no_channel_prefix_ignored(self):
        text = "This is just regular text without any channel prefix."
        result = parse_channel_messages(text)
        assert result == []

    def test_mixed_content(self):
        text = "Some thinking...\n[#daily-ops] 記得補貨\nMore thoughts..."
        result = parse_channel_messages(text)
        assert len(result) == 1
        assert result[0][0] == "daily-ops"

    def test_multiline_message_body(self):
        text = "[#management] 早安報告：\n- 庫存正常\n- 今日有 3 筆訂單\n[#shipping] 出貨提醒"
        result = parse_channel_messages(text)
        assert len(result) == 2
        assert result[0][0] == "management"
        assert "庫存正常" in result[0][1]
        assert "3 筆訂單" in result[0][1]
        assert result[1][0] == "shipping"
