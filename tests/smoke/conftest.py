"""Smoke test fixtures — require real Claude CLI + MiniMax API."""
import os
import pytest
from raisebull.runner import ClaudeRunner

SMOKE_REASON = "Requires ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN env vars"


def has_minimax_config() -> bool:
    return bool(os.environ.get("ANTHROPIC_BASE_URL")) and bool(
        os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )


smoke = pytest.mark.skipif(not has_minimax_config(), reason=SMOKE_REASON)


@pytest.fixture(scope="module")
def runner(tmp_path_factory):
    workspace = tmp_path_factory.mktemp("smoke_workspace")
    return ClaudeRunner(
        claude_bin="claude",
        workspace=str(workspace),
        model=os.environ.get("ANTHROPIC_MODEL", "MiniMax-M2.7"),
    )
