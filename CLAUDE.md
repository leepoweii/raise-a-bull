# raise-a-bull — Framework Development Guide

This is the **raise-a-bull framework repository**. You are helping build the open-source personal AI OS.

## What this repo is

- `src/raisebull/` — the pip-installable framework (runner, sessions, webhooks, heartbeat)
- `workspace/` — template that users copy and customize (NEVER commit user workspace data here)
- `docs/` — architecture decisions and guides

## What this repo is NOT

- Not a deployed bot instance — that's the user's private workspace
- Not Samantha's workspace — Samantha's config is private

## Key Architecture Decisions

1. **Claude Code is the only supported runner** (`claude -p`) — intentional gate for quality
2. **workspace/ is always private** — users copy the template, keep it local or in private repo
3. **sessions.db + workspace/ are volume-mounted** — survive every Docker rebuild
4. **Samantha is the dogfood deployment** — if it works for Samantha, it ships

## Runner Interface

```python
class BaseRunner:
    async def run(self, prompt: str, session_id: str | None = None) -> RunResult: ...

class ClaudeRunner(BaseRunner):
    # Wraps: claude -p --add-dir workspace/ [prompt]
```

## Webhook Flow

```
LINE/Discord message → FastAPI → handler → runner.run() → reply
                                ↑
                         show_loading_animation() first (LINE only)
```

## Skills System

workspace/skills/ — files loaded via `claude -p --add-dir workspace/`

Loading modes (defined in skill frontmatter):
- `always` — injected every run
- `heartbeat` — heartbeat context only  
- `on-demand` — triggered by keywords in message

## Development

```bash
cd ~/raise-a-bull
uv sync
uv run pytest tests/ -v
```

## Coding Standards

- Python 3.11+, uv for package management
- FastAPI for webhook server
- APScheduler for heartbeat
- SQLite for session persistence (simple, portable)
- All async
- Tests first (TDD)
