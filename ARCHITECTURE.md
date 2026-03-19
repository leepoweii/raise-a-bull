# raise-a-bull Architecture

## Mental Model

**Engine + Context = Bot**

The engine (`~/raise-a-bull/`) is shared and never modified per-instance.
The context (`~/bots/<name>/workspace/`) is everything that makes a bot unique.

This is the same pattern as opening different repos in an IDE — one tool, many projects.

---

## Directory Layout

```
~/raise-a-bull/               ← Engine (this repo)
│   ├── docker-compose.yml    ← Parameterized: BOT_NAME, BOT_PORT, WORKSPACE_PATH, BOT_ENV_FILE
│   ├── Dockerfile
│   ├── entrypoint.sh         ← Startup: credentials, MiniMax config, workspace seed
│   ├── workspace.example/    ← Template for new instances
│   └── src/raisebull/        ← FastAPI app source
│
~/bots/
│   ├── start-bot.sh          ← Launch helper: bash start-bot.sh <name>
│   ├── daniu/                ← Bot instance: 小牛
│   │   ├── .env              ← Compose vars + secrets (never committed)
│   │   └── workspace/        ← Full context for this instance
│   └── work/                 ← Bot instance: work assistant
│       ├── .env
│       └── workspace/
```

---

## Layers

### Layer 0 — Host

`start-bot.sh` is the single entry point. It reads three compose-level vars from the instance `.env`:

```bash
BOT_NAME=daniu
BOT_PORT=18888
WORKSPACE_PATH=/home/yourname/bots/daniu/workspace
```

Then runs:

```bash
docker compose -p "bull-daniu" up -d --build
```

The `-p bull-daniu` project name namespaces all Docker volumes automatically:
- `bull-daniu_bot-claude` → Claude credentials + MiniMax config

Each instance is fully isolated — different container name, port, workspace, and volumes.

---

### Layer 1 — Docker Compose

```yaml
container_name: bull-${BOT_NAME}
ports:    "${BOT_PORT}:8000"
env_file: ${BOT_ENV_FILE}            # full path to instance .env
volumes:
  - ${WORKSPACE_PATH}:/app/workspace  # context (bind mount — lives on host)
  - bot-claude:/home/bull/.claude     # Claude config (named volume)
```

The workspace bind mount means the context directory is always readable and editable directly on the host. No need to exec into the container to change identity or memory files.

---

### Layer 2 — entrypoint.sh

Runs on every container start, in order:

1. **Claude credentials** — if `CLAUDE_CREDENTIALS` is set and `.credentials.json` does not yet exist, decode base64 → write to `/home/bull/.claude/.credentials.json`
2. **MiniMax config** — if `MINIMAX_API_KEY` is set, write `/home/bull/.claude/settings.json` with the MiniMax base URL, auth token, and model names (idempotent — overwrites every start)
3. **Workspace seed** — if `/app/workspace` is empty, copy from `/app/workspace.example/` (first-deploy safety net)
4. **Handoff** → `uvicorn raisebull.main:app`

---

### Layer 3 — FastAPI App (`main.py`)

On startup, creates three singletons:

```python
SessionStore(db_path="/app/workspace/data/sessions.db")

ClaudeRunner(
    claude_bin = os.getenv("CLAUDE_BIN", "claude"),
    workspace  = os.getenv("WORKSPACE", "/app/workspace"),
    model      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
)
```

Then starts Discord bot (if token set) and heartbeat scheduler.

Routes:
- `GET  /health` — liveness check
- `POST /webhook/line` — LINE webhook (signature-verified, async)
- `POST /internal/discord/push` — push to Discord channel
- `POST /internal/heartbeat/trigger` — manual heartbeat tick

---

### Layer 4 — ClaudeRunner (`runner.py`)

Builds and runs this command:

```bash
claude -p "{prompt}" \
  --output-format stream-json \
  --dangerously-skip-permissions \
  --model MiniMax-M2.7 \
  --add-dir /app/workspace \
  --resume {session_id}
```

- `--add-dir /app/workspace` — Claude Code treats workspace as the project root and reads `CLAUDE.md` automatically
- `--resume {session_id}` — continues the previous conversation if session_id exists in SQLite
- Parses `stream-json` output to extract text, session_id, and token counts

---

### Layer 5 — Context (`workspace/`)

This is the only layer the user directly edits.

```
workspace/
├── CLAUDE.md                ← Claude Code entry point
│     @identity/profile.md
│     @identity/context.md
│     @identity/expertise.md
│     --- (engine instructions below)
│
├── identity/
│   ├── profile.md           ← Bot name, personality, tone
│   ├── context.md           ← About the owner and their world
│   └── expertise.md         ← What this instance specializes in
│
├── memory/                  ← Persistent memory files (written by Claude)
├── skills/                  ← Loadable skill documents
└── data/
    └── sessions.db          ← SQLite: session_id + token count per chat
```

`CLAUDE.md` uses `@include` syntax to pull in all three identity files at the top, so Claude Code receives them as part of the system context on every message. The engine instructions (memory/skills usage, group chat handling) follow below.

The `@identity/` files are the only things a user needs to fill in when creating a new instance.

---

## A Message — End to End

```
LINE user sends message
  │
  ▼
LINE Platform → POST /webhook/line
  │
  ▼
webhook_line.py
  ├── _resolve_context()        DM → session key: line:{user_id}
  │                             Group → session key: line:group:{group_id}
  │                                     prompt prefixed with [用戶 {uid}]:
  │
  ├── sessions.get()            fetch existing session_id from SQLite
  │
  ├── show_loading_animation()  DM only (LINE API limitation)
  │
  ▼
ClaudeRunner.run(prompt, session_id)
  │
  ▼
claude -p "..." --resume {session_id} --add-dir /app/workspace
  │
  ├── reads workspace/CLAUDE.md
  │     → @identity/profile.md, context.md, expertise.md
  │     → engine instructions
  ├── reads memory/ (relevant files)
  └── loads skills/ (as needed)
  │
  ▼
stream-json response parsed → text + new session_id + token counts
  │
  ▼
_send()
  ├── reply_token (fast, ~30s TTL)
  └── push_message to chat_id (fallback if token expired)
  │
  ▼
sessions.save()   store new session_id + cumulative token count
```

---

## Storage

| What | Where | Managed by |
|------|-------|------------|
| Identity, skills | `workspace/identity/`, `workspace/skills/` | You (edit directly) |
| Long-term memory | `workspace/memory/` | Claude (writes), you (can edit) |
| Session cache | `workspace/data/sessions.db` | FastAPI (SQLite) |
| Claude credentials | `bull-{name}_bot-claude` Docker volume | entrypoint.sh |
| MiniMax config | `bull-{name}_bot-claude` Docker volume | entrypoint.sh |

Because workspace is a bind mount, you can back up, version-control, or move an entire instance by copying its `workspace/` directory.

---

## Adding a New Instance

```bash
# 1. Create instance dir
mkdir -p ~/bots/<name>

# 2. Copy .env template, fill in secrets + compose vars
cp ~/raise-a-bull/.env.example ~/bots/<name>/.env

# 3. Seed workspace from template
cp -r ~/raise-a-bull/workspace.example/. ~/bots/<name>/workspace/

# 4. Fill in identity
$EDITOR ~/bots/<name>/workspace/identity/profile.md
$EDITOR ~/bots/<name>/workspace/identity/context.md

# 5. Start
bash ~/bots/start-bot.sh <name>
```

## Current Instances

| Bot | Container | Port | Stack | Notes |
|-----|-----------|------|-------|-------|
| 小牛 (培力站) | `bull-daniu` | 18888 | raise-a-bull | MiniMax M2.7 backend |
| 小茉 (MOJO BAR) | `mojo-openclaw` | 18889 | openclaw (legacy) | Future: migrate to raise-a-bull |
