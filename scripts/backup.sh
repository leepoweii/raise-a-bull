#!/usr/bin/env bash
set -euo pipefail

# Backup a bull workspace
# Usage: ./scripts/backup.sh [--full] [bull-root-path]
# Note: accepts bull root (~/bulls/X/), derives workspace as ~/bulls/X/workspace/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
FULL=false
BULL_ROOT=""

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<'EOF'
backup.sh — Backup a bull workspace

Usage:
  ./scripts/backup.sh [--full] [bull-root-path]

Modes:
  (default)    Config backup: bull.json, params.json, SOUL.md, USER.md,
               TOOLS.md, IDENTITY.md, skills/local/, identity/local/,
               managed-state.json
  --full       All of above PLUS memory/, MEMORY.md, logs/

Options:
  --help       Show this help message

Arguments:
  bull-root-path   Path to bull root (e.g. ~/bulls/my-bull/)
                   If omitted, searches current directory for bull.json

Output:
  Creates: $BULL_ROOT/.backups/bull-{INSTANCE_ID}-{TIMESTAMP}.tar.gz
  Never backs up: secrets/ (user must handle separately)

Examples:
  ./scripts/backup.sh ~/bulls/my-bull/
  ./scripts/backup.sh --full ~/bulls/my-bull/
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --full)     FULL=true; shift ;;
    --help|-h)  usage ;;
    *)
      if [[ -z "$BULL_ROOT" ]]; then
        BULL_ROOT="$1"; shift
      else
        echo "ERROR: Unknown argument: $1" >&2
        echo "Run with --help for usage." >&2
        exit 1
      fi
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Locate bull root
# ---------------------------------------------------------------------------
if [[ -z "$BULL_ROOT" ]]; then
  if [[ -f "./bull.json" ]]; then
    # Current dir is workspace
    BULL_ROOT="$(cd .. && pwd)"
  elif [[ -f "./workspace/bull.json" ]]; then
    BULL_ROOT="$(pwd)"
  else
    echo "ERROR: No bull-root-path provided and no bull.json found in current directory." >&2
    echo "Usage: ./scripts/backup.sh [--full] <bull-root-path>" >&2
    exit 1
  fi
fi

# Resolve to absolute path
BULL_ROOT="$(cd "$BULL_ROOT" 2>/dev/null && pwd)" || {
  echo "ERROR: Bull root path does not exist: $BULL_ROOT" >&2
  exit 1
}

WORKSPACE="$BULL_ROOT/workspace"

# Validate workspace
if [[ ! -f "$WORKSPACE/bull.json" ]]; then
  echo "ERROR: bull.json not found at $WORKSPACE/bull.json" >&2
  echo "Is '$BULL_ROOT' a valid bull root?" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Read configuration
# ---------------------------------------------------------------------------
INSTANCE_ID=$(jq -r '.instance_id' "$WORKSPACE/bull.json")
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
TIMESTAMP_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo ""
echo "  backup.sh — backing up bull workspace"
echo ""
echo "  Bull:       $INSTANCE_ID"
echo "  Workspace:  $WORKSPACE"
echo "  Mode:       $(if $FULL; then echo 'full'; else echo 'config'; fi)"
echo ""

# ---------------------------------------------------------------------------
# Build file list for tar
# ---------------------------------------------------------------------------
FILE_LIST=()

# Config files (always included)
CONFIG_FILES=(
  "bull.json"
  "params.json"
  "SOUL.md"
  "IDENTITY.md"
  "managed-state.json"
)

# Optional config files
OPTIONAL_CONFIG_FILES=(
  "USER.md"
  "TOOLS.md"
)

# Add config files that exist
for f in "${CONFIG_FILES[@]}"; do
  if [[ -f "$WORKSPACE/$f" ]]; then
    FILE_LIST+=("$f")
  fi
done

for f in "${OPTIONAL_CONFIG_FILES[@]}"; do
  if [[ -f "$WORKSPACE/$f" ]]; then
    FILE_LIST+=("$f")
  fi
done

# Add directories that exist
if [[ -d "$WORKSPACE/skills/local" ]]; then
  FILE_LIST+=("skills/local")
fi

if [[ -d "$WORKSPACE/identity/local" ]]; then
  FILE_LIST+=("identity/local")
fi

# Full mode: add memory, MEMORY.md, logs
if $FULL; then
  if [[ -d "$WORKSPACE/memory" ]]; then
    FILE_LIST+=("memory")
  fi

  if [[ -f "$WORKSPACE/MEMORY.md" ]]; then
    FILE_LIST+=("MEMORY.md")
  fi

  if [[ -d "$WORKSPACE/logs" ]]; then
    FILE_LIST+=("logs")
  fi
fi

# ---------------------------------------------------------------------------
# Create backup
# ---------------------------------------------------------------------------
BACKUP_DIR="$BULL_ROOT/.backups"
mkdir -p "$BACKUP_DIR"

BACKUP_FILE="$BACKUP_DIR/bull-${INSTANCE_ID}-${TIMESTAMP}.tar.gz"

echo "  Creating archive..."
echo "  Files:"
for f in "${FILE_LIST[@]}"; do
  echo "    - $f"
done
echo ""

# tar with relative paths from workspace root
tar -czf "$BACKUP_FILE" -C "$WORKSPACE" "${FILE_LIST[@]}"

# ---------------------------------------------------------------------------
# Update managed-state.json with last_backup_at
# ---------------------------------------------------------------------------
TMP_STATE=$(mktemp)
jq --arg ts "$TIMESTAMP_ISO" '.last_backup_at = $ts' "$WORKSPACE/managed-state.json" > "$TMP_STATE"
mv "$TMP_STATE" "$WORKSPACE/managed-state.json"

# Pretty-print
TMP_STATE=$(mktemp)
jq '.' "$WORKSPACE/managed-state.json" > "$TMP_STATE" && mv "$TMP_STATE" "$WORKSPACE/managed-state.json"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1 | tr -d '[:space:]')

echo "  ============================================"
echo "  Backup complete!"
echo "  ============================================"
echo ""
echo "  Bull:       $INSTANCE_ID"
echo "  Mode:       $(if $FULL; then echo 'full'; else echo 'config'; fi)"
echo "  File:       $BACKUP_FILE"
echo "  Size:       $BACKUP_SIZE"
echo ""
echo "  NOTE: secrets/ is NOT included. Back up secrets separately."
echo ""
