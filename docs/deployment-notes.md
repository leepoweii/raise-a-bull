# Deployment Notes — Docker Gotchas

Lessons learned deploying raise-a-bull on Docker for the first time (大牛, 2026-03-19).

---

## 1. CLAUDE_BIN must be `claude`, not a host path

```env
# ❌ Wrong — host path doesn't exist inside container
CLAUDE_BIN=/home/samantha-machine/.local/bin/claude

# ✅ Correct — npm installs claude to /usr/bin/claude, which is in PATH
CLAUDE_BIN=claude
```

## 2. Claude credentials must be mounted into the container

Claude auth lives in `~/.claude/.credentials.json` on the host. The container has no login state.

```yaml
# docker-compose.yml
volumes:
  - /home/YOUR_USER/.claude/.credentials.json:/root/.claude/.credentials.json:ro
```

If missing: every `claude -p` call returns `Not logged in · Please run /login` and the bot replies with an error.

## 3. Workspace must NOT be read-only

Skills write to `workspace/memory/`. If mounted `:ro`, Claude exits with code 1 mid-conversation.

```yaml
# ❌ Wrong
- ./workspace:/app/workspace:ro

# ✅ Correct
- ./workspace:/app/workspace
```

## 4. `docker compose restart` does NOT re-read env_file

Changes to `.env` require a full container recreation:

```bash
# ❌ Doesn't pick up .env changes
docker compose restart

# ✅ Forces re-read of env_file
docker compose up -d --force-recreate
```

## 5. Dockerfile must copy README.md before `uv sync`

hatchling reads `README.md` during build. If it's not present, build fails with `OSError: Readme file does not exist`.

```dockerfile
# ✅ Correct order
COPY pyproject.toml README.md ./
COPY src/ src/
RUN uv sync --no-dev
```

## 6. Claude reads CLAUDE.md from the working directory, not from `--add-dir`

`--add-dir workspace/` only grants file access — it does NOT cause Claude to read `workspace/CLAUDE.md` as system context.

The fix: set `cwd=workspace` when spawning the subprocess so Claude's directory-walk picks up `CLAUDE.md`.

```python
# runner.py
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdin=DEVNULL,
    stdout=PIPE,
    stderr=PIPE,
    cwd=self.workspace if self.workspace else None,  # ← critical
)
```

Without this, the bot responds as generic Claude with no personality.

## 7. LINE webhook path changed from openclaw

Old openclaw path: `POST /line/webhook`  
raise-a-bull path: `POST /webhook/line`

Update this in the LINE Developers Console under Messaging API → Webhook URL.
