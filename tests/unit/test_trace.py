"""Unit tests for stream-json → TraceStep parsing."""
import json
import pytest
from raisebull.trace import TraceStep, parse_stream_event


class TestParseStreamEvent:
    def test_thinking_event(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [{"type": "thinking", "thinking": "Let me analyze this..."}]
            },
        }
        steps = parse_stream_event(json.dumps(event).encode())
        assert len(steps) == 1
        assert steps[0].step_type == "thinking"
        assert steps[0].content == "Let me analyze this..."

    def test_tool_use_event(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_123",
                        "name": "Read",
                        "input": {"file_path": "/app/workspace/brand.md"},
                    }
                ]
            },
        }
        steps = parse_stream_event(json.dumps(event).encode())
        assert len(steps) == 1
        assert steps[0].step_type == "tool_call"
        assert steps[0].content["name"] == "Read"
        assert steps[0].content["input"]["file_path"] == "/app/workspace/brand.md"

    def test_tool_result_event(self):
        event = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_123",
                        "content": "# Brand Guide\nWe are 金美麥...",
                    }
                ]
            },
        }
        steps = parse_stream_event(json.dumps(event).encode())
        assert len(steps) == 1
        assert steps[0].step_type == "tool_result"
        assert "金美麥" in steps[0].content

    def test_text_event(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [{"type": "text", "text": "根據品牌文件..."}]
            },
        }
        steps = parse_stream_event(json.dumps(event).encode())
        assert len(steps) == 1
        assert steps[0].step_type == "text"
        assert steps[0].content == "根據品牌文件..."

    def test_mixed_content_blocks(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "Hmm..."},
                    {"type": "text", "text": "Here is the answer."},
                ]
            },
        }
        steps = parse_stream_event(json.dumps(event).encode())
        assert len(steps) == 2
        assert steps[0].step_type == "thinking"
        assert steps[1].step_type == "text"

    def test_result_event_returns_empty(self):
        event = {
            "type": "result",
            "session_id": "abc",
            "cost_usd": 0.01,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }
        steps = parse_stream_event(json.dumps(event).encode())
        assert steps == []

    def test_malformed_json_returns_empty(self):
        steps = parse_stream_event(b"not json at all")
        assert steps == []

    def test_empty_content_returns_empty(self):
        event = {"type": "assistant", "message": {"content": []}}
        steps = parse_stream_event(json.dumps(event).encode())
        assert steps == []

    def test_unknown_content_type_skipped(self):
        event = {
            "type": "assistant",
            "message": {
                "content": [{"type": "image", "source": {"data": "..."}}]
            },
        }
        steps = parse_stream_event(json.dumps(event).encode())
        assert steps == []
