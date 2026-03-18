# Zeabur One-Click Deploy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable non-technical Type B users to deploy raise-a-bull to Zeabur with one click, filling in only LINE API keys and an Anthropic API key.

**Architecture:** Three changes to the repo — (1) make the port configurable from `$PORT` env var, (2) support `ANTHROPIC_API_KEY` for cloud auth (no credentials.json needed), (3) add `template.yaml` for the Zeabur marketplace and a deploy button. The Docker image already works; Zeabur builds it directly from the repo.

**Tech Stack:** Zeabur Git deploy, `template.yaml` (Zeabur v1), existing FastAPI/uvicorn/Docker stack.

**Working directory:** `samantha-wsl:~/raise-a-bull`

---

## Task 1: Make PORT configurable

Zeabur injects a `$PORT` env var. The app must read it instead of hardcoding 8000.

**Files:**
- Modify: `Dockerfile`
- Modify: `src/raisebull/main.py` (add PORT reading)

**Step 1: Update Dockerfile CMD to use $PORT**

```dockerfile
CMD ["sh", "-c", "uv run uvicorn raisebull.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

Replace the existing CMD line in `Dockerfile`.

**Step 2: Verify it still works locally**

```bash
docker compose up -d
curl http://localhost:8000/health
# Expected: {"status":"ok","version":"0.1.0"}
```

**Step 3: Commit**

```bash
git add Dockerfile
git commit -m "fix: read PORT from env var (required for Zeabur)"
```

---

## Task 2: Support ANTHROPIC_API_KEY for cloud auth

Local deploy uses OAuth credentials (`~/.claude/.credentials.json`). Zeabur users have no way to mount that file — they need API key auth instead. Claude Code already supports `ANTHROPIC_API_KEY` env var natively; no code changes needed. Just document and expose it in the template.

**Verification — confirm Claude Code uses ANTHROPIC_API_KEY:**

```bash
docker exec bull-daniu sh -c 'ANTHROPIC_API_KEY=test claude -p "hi" --output-format stream-json --verbose 2>&1 | head -3'
# Should attempt to call API (will fail with invalid key error, not auth error)
```

No code changes needed if confirmed. If Claude Code ignores the env var and only uses credentials, we would need a startup script — but this is very unlikely given Claude Code's design.

**Step 1: Note finding in commit message and move on**

```bash
git commit --allow-empty -m "docs: ANTHROPIC_API_KEY supported by Claude Code natively — no code change needed"
```

---

## Task 3: Add workspace.example as default WORKSPACE for cloud deploy

On Zeabur there is no persistent filesystem for the workspace directory between builds. The `workspace.example/` in the repo is the fallback. We need the app to default to `/app/workspace.example` if `WORKSPACE` is not set (instead of requiring it).

**Files:**
- Modify: `src/raisebull/main.py` (change WORKSPACE default)
- Modify: `Dockerfile` (copy workspace.example into image)

**Step 1: Copy workspace.example into Docker image**

Add to `Dockerfile` before the CMD line:

```dockerfile
# Copy workspace template as fallback for cloud deployments
COPY workspace.example/ /app/workspace.example/
```

**Step 2: Change WORKSPACE default in main.py**

In `lifespan()`, change:
```python
# Before:
workspace=os.getenv("WORKSPACE", "/app/workspace"),

# After:
workspace=os.getenv("WORKSPACE", "/app/workspace.example"),
```

**Step 3: Verify locally**

```bash
docker compose up -d --build
docker exec bull-daniu ls /app/workspace.example/
# Should show CLAUDE.md and skills/ etc.
```

**Step 4: Commit**

```bash
git add Dockerfile src/raisebull/main.py
git commit -m "feat: bundle workspace.example in image as default WORKSPACE for cloud deploy"
```

---

## Task 4: Create template.yaml

This is the Zeabur marketplace template definition. It declares the service, all env vars (with descriptions for users), and the deploy button URL.

**Files:**
- Create: `template.yaml`

**Step 1: Create template.yaml**

```yaml
apiVersion: zeabur.com/v1
kind: Template
metadata:
    name: raise-a-bull
spec:
    description: Personal AI bot for LINE and Discord powered by Claude Code
    icon: https://raw.githubusercontent.com/leepoweii/raise-a-bull/main/docs/assets/icon.png
    tags:
        - AI
        - Bot
        - LINE
    readme: |-
        # raise-a-bull

        Personal AI operating system for LINE and Discord built around Claude Code.

        ## Requirements
        - Anthropic API key (paid account)
        - LINE Messaging API channel (free)

        ## Setup
        1. Fill in your LINE channel credentials below
        2. Set your Anthropic API key
        3. Deploy — your bot will be live in ~2 minutes
        4. Set the webhook URL in LINE Developers Console to:
           `https://<your-domain>/webhook/line`
    services:
        - name: raise-a-bull
          template: GIT
          spec:
            source:
                githubRepository: leepoweii/raise-a-bull
            ports:
                - id: web
                  port: 8000
                  type: HTTP
            env:
                # Claude
                ANTHROPIC_API_KEY:
                    default: ""
                    expose: false
                CLAUDE_MODEL:
                    default: claude-sonnet-4-6
                    expose: false
                # LINE
                LINE_CHANNEL_SECRET:
                    default: ""
                    expose: false
                LINE_CHANNEL_ACCESS_TOKEN:
                    default: ""
                    expose: false
                LINE_USER_ID:
                    default: ""
                    expose: false
                # Discord (optional)
                DISCORD_BOT_TOKEN:
                    default: ""
                    expose: false
                DISCORD_GUILD_ID:
                    default: ""
                    expose: false
                # Internal
                DB_PATH:
                    default: /app/data/sessions.db
                    expose: false
    variables:
        - key: LINE_CHANNEL_SECRET
          type: STRING
          name: LINE Channel Secret
          description: From LINE Developers Console → Basic Settings → Channel secret
        - key: LINE_CHANNEL_ACCESS_TOKEN
          type: STRING
          name: LINE Channel Access Token
          description: From LINE Developers Console → Messaging API → Channel access token
        - key: ANTHROPIC_API_KEY
          type: STRING
          name: Anthropic API Key
          description: Your Anthropic API key from console.anthropic.com

localization:
    zh-TW:
        description: 基於 Claude Code 的個人 AI 助理，支援 LINE 和 Discord
```

**Step 2: Commit**

```bash
git add template.yaml
git commit -m "feat: add Zeabur template.yaml for one-click deploy"
```

---

## Task 5: Publish template and add deploy button

**Step 1: Install Zeabur CLI and publish**

```bash
npx zeabur@latest template create -f template.yaml
# Output: INFO Template "raise-a-bull" (https://zeabur.com/templates/XXXXXX) created
# Save the template ID from the output
```

**Step 2: Update template.yaml with the template URL (for reference)**

Add a comment at the top of template.yaml:
```yaml
# Published at: https://zeabur.com/templates/XXXXXX
```

**Step 3: Add deploy button to README.md**

Add near the top of README.md:

```markdown
[![Deploy to Zeabur](https://zeabur.com/button.svg)](https://zeabur.com/create?template=XXXXXX)
```

**Step 4: Commit**

```bash
git add template.yaml README.md
git commit -m "feat: publish Zeabur template — one-click deploy button in README"
git push
```

---

## Verification

After deploy, set the webhook in LINE Developers Console:
```
https://<zeabur-domain>/webhook/line
```

Click Verify → should show Success. Send the bot a message → should respond within 30s.

**Common Zeabur issues:**
- Build fails → check `docker logs` equivalent in Zeabur dashboard
- Bot not responding → verify `LINE_CHANNEL_SECRET` and `LINE_CHANNEL_ACCESS_TOKEN` are set correctly
- Claude not responding → verify `ANTHROPIC_API_KEY` is valid and has credits
