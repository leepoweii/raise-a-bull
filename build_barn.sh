#!/usr/bin/env bash
# build_barn.sh — Idempotent dependency installer for raise-a-bull
# Usage: bash build_barn.sh
# Called by Claude subagent during onboarding. No interactive prompts.
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓ $1${NC}"; }
fail() { echo -e "${RED}✗ $1${NC}" >&2; exit 1; }

detect_platform() {
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "macos"
    elif grep -qi microsoft /proc/version 2>/dev/null; then
        echo "wsl"
    else
        fail "Unsupported platform. Supported: macOS, WSL (Windows Subsystem for Linux)"
    fi
}

PLATFORM=$(detect_platform)
echo "Platform: $PLATFORM"

# ── 1. Homebrew ───────────────────────────────────────────────
if command -v brew &>/dev/null; then
    ok "Homebrew (already installed)"
else
    echo "Installing Homebrew..."
    NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add brew to PATH for this script session
    if [[ "$PLATFORM" == "wsl" ]]; then
        eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
    else
        if [[ -x /opt/homebrew/bin/brew ]]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [[ -x /usr/local/bin/brew ]]; then
            eval "$(/usr/local/bin/brew shellenv)"
        else
            fail "Homebrew installed but brew binary not found in /opt/homebrew or /usr/local"
        fi
    fi
    ok "Homebrew"
fi

# Ensure brew is on PATH if it was pre-installed but not in the session environment
if [[ "$PLATFORM" == "wsl" ]] && [[ -d /home/linuxbrew/.linuxbrew ]] && ! command -v brew &>/dev/null; then
    eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
fi

# brew_install <pkg> [--cask]
# Idempotent: skips if formula or cask is already installed, or binary is on PATH.
brew_install() {
    local pkg="$1"
    local flag="${2:-}"
    # Check formula install, cask install, or binary presence — whichever applies
    if brew list --formula "$pkg" &>/dev/null || \
       brew list --cask "$pkg" &>/dev/null || \
       command -v "$pkg" &>/dev/null; then
        ok "$pkg (already installed)"
        return
    fi
    echo "Installing $pkg..."
    if [[ "$flag" == "--cask" ]]; then
        brew install --cask "$pkg"
    else
        brew install "$pkg"
    fi
    ok "$pkg"
}

# ── 2. Docker ─────────────────────────────────────────────────
# Step A: Ensure Docker is installed (cask check separate from daemon check)
if [[ "$PLATFORM" == "macos" ]]; then
    if ! brew list --cask docker &>/dev/null; then
        echo "Installing Docker Desktop..."
        brew install --cask docker
        ok "Docker Desktop installed"
    else
        ok "Docker Desktop (already installed)"
    fi
    # Step B: Start daemon if not running
    if ! docker info &>/dev/null; then
        echo "Starting Docker Desktop..."
        open -a Docker
        echo "Waiting for Docker daemon (this may take ~30 seconds)..."
        timeout=120
        elapsed=0
        until docker info &>/dev/null; do
            sleep 2
            elapsed=$((elapsed + 2))
            if [[ $elapsed -ge $timeout ]]; then
                fail "Docker daemon did not start within ${timeout}s. Open Docker Desktop manually and re-run."
            fi
        done
    fi
    ok "Docker"
else
    # WSL: install docker CLI via brew, daemon comes from Docker Desktop for Windows
    if ! brew list --formula docker &>/dev/null; then
        echo "Installing docker (CLI)..."
        brew install docker
        ok "docker"
    else
        ok "docker (already installed)"
    fi
    if ! docker info &>/dev/null; then
        echo ""
        echo "⚠️  Docker daemon not running."
        echo "   On WSL: open Docker Desktop (Windows) → Settings → Resources → WSL Integration"
        echo "   → enable your distro → Apply & Restart."
        echo "   Then re-run build_barn.sh."
        fail "Docker daemon not available"
    fi
    ok "Docker"
fi

# ── 3. Node.js ────────────────────────────────────────────────
brew_install node

# ── 4. gum ───────────────────────────────────────────────────
brew_install gum

# ── 5. gh (GitHub CLI) ──────────────────────────────
brew_install gh

# ── 6. cloudflared ───────────────────────────────────
brew_install cloudflared

# ── 7. Docker network (agents-net) ────────────────────────────
# docker-compose.yml declares agents-net as external: true.
# Create it if missing so docker compose up doesn't fail silently.
if ! docker network inspect agents-net &>/dev/null; then
    echo "Creating Docker network: agents-net"
    docker network create agents-net
fi
ok "Docker network: agents-net"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "build_barn.sh complete."
echo "All dependencies ready."
