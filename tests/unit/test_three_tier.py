"""Unit tests for three-tier Discord response state machine."""
import pytest
from time import time
from raisebull.discord_bot import ChannelState, should_respond, TIMEOUT


class TestChannelState:
    def test_default_is_silent(self):
        state = ChannelState()
        assert state.active is False

    def test_mention_activates(self):
        state = ChannelState()
        state.on_mention()
        assert state.active is True

    def test_message_in_active_resets_timer(self):
        state = ChannelState()
        state.on_mention()
        t1 = state.last_active
        state.on_message()
        assert state.last_active >= t1

    def test_timeout_deactivates(self):
        state = ChannelState()
        state.on_mention()
        state.last_active = time() - TIMEOUT - 1
        state.check_timeout()
        assert state.active is False

    def test_no_timeout_if_recent(self):
        state = ChannelState()
        state.on_mention()
        state.check_timeout()
        assert state.active is True

    def test_silent_state_ignores_regular_message(self):
        state = ChannelState()
        assert should_respond(state, mentioned=False) is False

    def test_active_state_responds_to_regular_message(self):
        state = ChannelState()
        state.on_mention()
        assert should_respond(state, mentioned=False) is True

    def test_mention_always_triggers_response(self):
        state = ChannelState()
        assert should_respond(state, mentioned=True) is True

    def test_should_respond_is_pure_check(self):
        """should_respond must NOT mutate state — caller handles activation."""
        state = ChannelState()
        assert state.active is False
        should_respond(state, mentioned=True)
        assert state.active is False

    def test_timeout_then_mention_reactivates(self):
        state = ChannelState()
        state.on_mention()
        state.last_active = time() - TIMEOUT - 1
        state.check_timeout()
        assert state.active is False
        state.on_mention()
        assert state.active is True
