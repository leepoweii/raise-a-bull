# Future Improvements

Lessons from onboarding test (2026-03-19). Implement when ready.

---

## 1. Cloudflare Tunnel Setup in Install Guide

**Problem:** `build_barn.sh` installs cloudflared, but the install guide doesn't cover tunnel configuration. The user had to figure out creating tunnels, adding hostnames to config, and routing DNS on their own.

**What to add:**
- Phase in install guide for tunnel setup (not just "choose quick or named")
- For named tunnels: `cloudflared tunnel create`, add hostname to `~/.cloudflared/config.yml`, `cloudflared tunnel route dns`
- Detect existing config and offer to add a new hostname entry
- For quick tunnels: clear instructions that URL changes on restart

---

## 2. Web Search API as MCP Tool

**Problem:** MiniMax model can't use Claude's built-in WebSearch (server-side Anthropic feature). Bots on MiniMax lose web search capability entirely.

**Solution:** Add an optional web search MCP server so any model can search the web.

**Options:**
- [Tavily MCP](https://github.com/tavily-ai/tavily-mcp) — dedicated search API
- [Serper](https://serper.dev/) — Google SERP API
- Custom MCP wrapper around any search provider

**Implementation ideas:**
- Optional `--search-api=tavily` flag in `raise_bull.sh`
- Collect API key via gum, write to `.env`
- Configure MCP server in container's Claude settings (`/home/bull/.claude/settings.json`)
- Or bake a default search MCP into the Docker image

---

## 3. Full TUI Startup (gum-based interactive setup)

**Problem:** Current onboarding requires Claude Code to orchestrate. Works well but adds a dependency on Claude Code being available and understanding the guide.

**Idea:** A standalone `setup.sh` using gum for the entire flow — no Claude Code needed for onboarding.

**Flow:**
```
$ bash setup.sh
? Project name: ox
? Bot name: oxy
? Port [18888]:
? Tunnel type: (named / quick)
? Tunnel domain: oxy.pwlee.xyz
? Enable Discord? (y/N)
? Enable MiniMax? (y/N)

Installing dependencies... ✓
Cloning engine... ✓
Enter secrets below (paste into terminal):
? LINE Channel Secret: ********
? LINE Access Token: ********
? LINE User ID (optional):
? MiniMax API Key: ********

Writing .env... ✓
Starting container... ✓
Waiting for health... ✓

✓ Bot running at https://oxy.pwlee.xyz/webhook/line
```

**Benefits:**
- Works without Claude Code subscription
- Single command, no back-and-forth
- Can still offer Claude Code guide as an alternative for users who want hand-holding

**Considerations:**
- Keeps `raise_bull.sh` and `build_barn.sh` as the backend — TUI is a wrapper
- LINE/Discord/Cloudflare console steps still need the user to do manually (show instructions via gum)
- Could use `gum confirm`, `gum choose`, `gum spin` for polished UX

---

## 4. Bot Skills & Tools Ecosystem

**Goal:** Build a library of skills and tools that bots can load from their workspace.

**What this means:**
- Skills = Claude Code skill documents (markdown prompts the bot can `@include`)
- Tools = MCP servers or bash scripts the bot can invoke

**Examples of useful skills:**
- `/remember` — structured memory management
- `/schedule` — set up recurring heartbeat messages
- `/search` — web search (wraps MCP tool from item #2)
- `/summarize-chat` — summarize recent LINE conversation history
- `/image` — generate or fetch images via agents-infra

**Examples of useful tools:**
- Calendar/reminder MCP
- File upload/download via agents-gateway
- Translation service
- Weather/news API wrapper

**Implementation:**
- Skills live in `workspace/skills/` per bot instance
- Shared skills can live in `engine/skills/` and get copied on seed
- Tools configured as MCP servers in the container's Claude settings
- `raise_bull.sh` could offer `--skills=search,image` to pre-install

---

## 5. agents-infra as Backend Services for Bots

**What exists:** `agents-infra` on samantha-wsl (GitHub: `leepoweii/agents-infra`, private) provides shared Docker services:
- `agents-gateway` (port 18892) — FastAPI: CDN upload, static file serving, screenshot proxy
- `agents-screenshot` (internal) — Playwright/Chromium HTML→image
- Public at `cdn.pwlee.xyz` via Cloudflare tunnel
- All services on `agents-net` Docker bridge network

**How bots can use it:**
- Bots already join `agents-net` — they can reach `agents-gateway` by container name
- Upload images, take screenshots, serve static files — all without external APIs
- Future: add more backend services (e.g. vector DB, cron scheduler, notification queue)

**Implementation plan:**
1. **Phase 1 — Direct HTTP calls (no auth):**
   - Add `GATEWAY_URL` env var to bot `.env` (e.g. `http://agents-gateway:18892` on same network, or `https://cdn.pwlee.xyz` for remote bots)
   - Bot skills/tools call gateway endpoints directly
   - Works now for same-network bots on samantha-wsl

2. **Phase 2 — API key auth:**
   - Add API key middleware to agents-gateway
   - `raise_bull.sh` collects gateway API key via gum
   - Enables remote bots (not on samantha-wsl) to call gateway securely

3. **Phase 3 — Expand services:**
   - Vector DB for bot memory search (RAG)
   - Cron/scheduler service for recurring tasks
   - Notification queue (push messages, email)
   - Shared knowledge base across bots

**Architecture:**
```
Bot (any machine)
  → agents-gateway (cdn.pwlee.xyz or agents-net)
    → agents-screenshot (internal)
    → future: vector-db, scheduler, etc.
```
