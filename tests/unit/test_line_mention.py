"""Unit tests for LINE @mention detection."""
import pytest
from raisebull.webhook_line import line_bot_is_mentioned


def _make_mention(is_self: bool):
    class Mentionee:
        def __init__(self, is_self):
            self.is_self = is_self
            self.type = "user"

    class Mention:
        def __init__(self, mentionees):
            self.mentionees = mentionees

    return Mention([Mentionee(is_self)])


class TestLineMentionDetection:
    def test_is_self_true(self):
        assert line_bot_is_mentioned(_make_mention(True)) is True

    def test_is_self_false(self):
        assert line_bot_is_mentioned(_make_mention(False)) is False

    def test_no_mention(self):
        assert line_bot_is_mentioned(None) is False

    def test_empty_mentionees(self):
        class EmptyMention:
            mentionees = []

        assert line_bot_is_mentioned(EmptyMention()) is False

    def test_multiple_mentionees_one_self(self):
        """Returns True if any mentionee is_self even with other non-self mentionees."""

        class Mentionee:
            def __init__(self, is_self):
                self.is_self = is_self

        class Mention:
            mentionees = [Mentionee(False), Mentionee(True)]

        assert line_bot_is_mentioned(Mention()) is True

    def test_multiple_mentionees_none_self(self):
        """Returns False when multiple non-self mentionees."""

        class Mentionee:
            def __init__(self, is_self):
                self.is_self = is_self

        class Mention:
            mentionees = [Mentionee(False), Mentionee(False)]

        assert line_bot_is_mentioned(Mention()) is False

    def test_mention_without_mentionees_attr(self):
        """Handles mention objects that have no mentionees attribute."""

        class BrokenMention:
            pass

        assert line_bot_is_mentioned(BrokenMention()) is False


class TestLinePrefixTrigger:
    def test_prefix_match_triggers(self):
        """Message starting with trigger prefix should be detected."""
        prefix = "小牛兒"
        assert "小牛兒 你好".startswith(prefix) is True

    def test_no_prefix_does_not_trigger(self):
        """Message without prefix should not trigger."""
        prefix = "小牛兒"
        assert "你好小牛兒".startswith(prefix) is False

    def test_prefix_strip(self):
        """After stripping prefix, only the actual request remains."""
        prefix = "小牛兒"
        text = "小牛兒 幫我查天氣"
        result = text[len(prefix):].strip()
        assert result == "幫我查天氣"

    def test_read_trigger_prefix_default(self):
        """When no settings file exists, return default."""
        from raisebull.webhook_line import _read_trigger_prefix
        assert _read_trigger_prefix("/nonexistent/path") == "小牛兒"

    def test_read_trigger_prefix_from_file(self, tmp_path):
        """Read prefix from settings.json."""
        import json
        from raisebull.webhook_line import _read_trigger_prefix
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text(json.dumps({"line_trigger_prefix": "牛牛"}))
        assert _read_trigger_prefix(str(tmp_path)) == "牛牛"
