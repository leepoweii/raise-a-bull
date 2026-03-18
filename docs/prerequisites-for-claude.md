---
name: raise-a-bull-prerequisites
description: Use when a user needs to set up accounts and install software before installing raise-a-bull. Covers Claude Max, LINE Developer, Cloudflare, Docker, Claude Code CLI, and cloudflared. Run this once ever per machine.
---

# raise-a-bull — Prerequisites

Run through this **once** before installing raise-a-bull. Everything here is a one-time setup — you won't need to repeat it for future bots.

Estimated time: 30–45 minutes.

---

## Part 1 — Accounts

### 1.1 Anthropic — Claude Max (required)

raise-a-bull runs `claude -p` under the hood. You need Claude Max.

1. Go to https://claude.ai and create an account
2. Upgrade to **Claude Max** (~$20/mo) — Settings → Plans
3. Verify by opening a conversation and confirming you're on Max

> Claude Max is the only requirement you pay for. Everything else below is free.

---

### 1.2 LINE Developer Account (required for LINE bot)

1. Create a personal **LINE account** if you don't have one — https://line.me
2. Go to https://developers.line.biz and sign in with your LINE account
3. Accept the Developer terms — you're now a LINE Developer

No credit card needed. Free tier handles thousands of messages/month.

---

### 1.3 Cloudflare Account (recommended)

Needed for a **permanent** webhook URL. Without it, your URL changes every time you restart.

1. Go to https://cloudflare.com → Sign Up — free plan is fine
2. You don't need to add a domain — the free `*.trycloudflare.com` URLs work for testing
3. For a permanent URL later, you'll add a domain you own

> Skip this for now if you just want to test. Come back when you want a stable URL.

---

### 1.4 Discord Developer Account (optional)

Only needed if you want the bot on Discord in addition to LINE.

1. Create a Discord account at https://discord.com — free
2. Go to https://discord.com/developers/applications — your developer dashboard is automatically available

---

## Part 2 — Software

Install in this order. Each step may depend on the previous.

---

### 2.1 Homebrew (Mac only)

Homebrew is a package manager for Mac. Skip if you're on Linux (use `apt` or `dnf` instead).

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Verify:
```bash
brew --version
# Homebrew 4.x.x
```

---

### 2.2 Git

**Mac:**
```bash
brew install git
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install git
```

Verify:
```bash
git --version
# git version 2.x.x
```

---

### 2.3 Docker

**Mac:** Download and install Docker Desktop from https://docker.com/products/docker-desktop

**Linux (Ubuntu):**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in after this
```

Start Docker Desktop (Mac) or verify the daemon is running (Linux):
```bash
docker --version        # Docker version 24+
docker compose version  # Docker Compose version v2+
```

> On Linux, if `docker compose` (with a space) isn't found, you have v1. Upgrade to Docker Engine 24+ which includes Compose v2 built in.

---

### 2.4 Node.js (needed for Claude Code CLI)

**Mac:**
```bash
brew install node
```

**Linux:**
```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install nodejs
```

Verify:
```bash
node --version   # v18+ or v20+
npm --version    # 9+
```

---

### 2.5 Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
```

**Verify the binary is in PATH:**
```bash
claude --version
# 2.x.x
```

> On some Linux setups, npm global binaries land in `~/.local/bin` which may not be in PATH. If `claude` is not found:
> ```bash
> echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
> source ~/.bashrc
> claude --version
> ```

**Log in to your Claude account:**
```bash
claude
# Follow the login prompt — opens browser, authorize with your Anthropic account
# Exit with Ctrl+C once logged in
```

Verify auth works:
```bash
claude -p "say hi" --output-format stream-json 2>&1 | head -2
# Should show {"type":"system",...} — not a login prompt
```

---

### 2.6 cloudflared (Cloudflare Tunnel)

**Mac:**
```bash
brew install cloudflare/cloudflare/cloudflared
```

**Linux:**
```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/
```

Verify:
```bash
cloudflared --version
# cloudflared version 202x.x.x
```

---

## Part 3 — Final Checklist

Run this to confirm everything is ready:

```bash
docker --version        && echo "✓ Docker"
docker compose version  && echo "✓ Docker Compose"
git --version           && echo "✓ Git"
node --version          && echo "✓ Node"
claude --version        && echo "✓ Claude Code CLI"
cloudflared --version   && echo "✓ cloudflared"
claude -p "say hi" --output-format stream-json 2>&1 | grep -q '"type":"system"' && echo "✓ Claude auth"
```

All seven lines should print ✓. If any fail, go back to that section.

---

## Ready

Once all checks pass, return to the install guide:

```
@docs/install-guide-for-claude.md

Help me install raise-a-bull.
```
