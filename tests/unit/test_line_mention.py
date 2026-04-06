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
