#!/usr/bin/env bash
set -euo pipefail

# Update managed skills + identity in a bull workspace
# Usage: ./scripts/feed.sh [--dry-run] [--force] [bull-root-path]
# Note: accepts bull root (~/bulls/X/), derives workspace as ~/bulls/X/workspace/

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DRY_RUN=false
FORCE=false
BULL_ROOT=""

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<'EOF'
feed.sh — Update managed skills + identity in a bull workspace

Usage:
  ./scripts/feed.sh [--dry-run] [--force] [bull-root-path]

Options:
  --dry-run    List files that would change, then exit
  --force      Overwrite locally modified managed files
  --help       Show this help message

Arguments:
  bull-root-path   Path to bull root (e.g. ~/bulls/my-bull/)
                   If omitted, searches current directory for bull.json

Examples:
  ./scripts/feed.sh ~/bulls/my-bull/
  ./scripts/feed.sh --dry-run ~/bulls/my-bull/
  ./scripts/feed.sh --force ~/bulls/my-bull/
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)  DRY_RUN=true; shift ;;
    --force)    FORCE=true; shift ;;
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
# Cross-platform sha256
# ---------------------------------------------------------------------------
sha256() {
  local file="$1"
  if command -v sha256sum &>/dev/null; then
    sha256sum "$file" | cut -d' ' -f1
  elif command -v shasum &>/dev/null; then
    shasum -a 256 "$file" | cut -d' ' -f1
  else
    echo "ERROR: No sha256 tool found (need sha256sum or shasum)" >&2
    exit 1
  fi
}

# ---------------------------------------------------------------------------
# Locate bull root
# ---------------------------------------------------------------------------
if [[ -z "$BULL_ROOT" ]]; then
  # Try to detect from current directory
  if [[ -f "./bull.json" ]]; then
    # Current dir is workspace
    BULL_ROOT="$(cd .. && pwd)"
  elif [[ -f "./workspace/bull.json" ]]; then
    BULL_ROOT="$(pwd)"
  else
    echo "ERROR: No bull-root-path provided and no bull.json found in current directory." >&2
    echo "Usage: ./scripts/feed.sh [--dry-run] [--force] <bull-root-path>" >&2
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

if [[ ! -f "$WORKSPACE/managed-state.json" ]]; then
  echo "ERROR: managed-state.json not found at $WORKSPACE/managed-state.json" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Read configuration
# ---------------------------------------------------------------------------
VERSION=$(cat "$REPO_ROOT/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
INSTANCE_ID=$(jq -r '.instance_id' "$WORKSPACE/bull.json")
REGION=$(jq -r '.region // "kinmen"' "$WORKSPACE/bull.json")

# Get installed skills list from bull.json
SKILLS_LIST=$(jq -r '.skills_installed[]' "$WORKSPACE/bull.json" 2>/dev/null || true)

# Source paths in the repo
REPO_SKILLS="$REPO_ROOT/skills"
REPO_IDENTITY="$REPO_ROOT/identity/regions/$REGION"

echo ""
echo "  feed.sh — updating managed files"
echo ""
echo "  Bull:       $INSTANCE_ID"
echo "  Workspace:  $WORKSPACE"
echo "  Mode:       $(if $DRY_RUN; then echo 'dry-run'; elif $FORCE; then echo 'force'; else echo 'safe'; fi)"
echo ""

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------
COUNT_NEW=0
COUNT_UPDATED=0
COUNT_SKIPPED=0

# ---------------------------------------------------------------------------
# Dry-run: compare and list changes
# ---------------------------------------------------------------------------
compare_file() {
  local src="$1"    # source file in repo
  local dst="$2"    # destination file in workspace
  local label="$3"  # display label
  local state_key="$4"  # key in managed-state.json (empty for identity)

  if [[ ! -f "$src" ]]; then
    return
  fi

  local src_checksum
  src_checksum=$(sha256 "$src")

  if [[ ! -f "$dst" ]]; then
    echo "    NEW:     $label"
    COUNT_NEW=$((COUNT_NEW + 1))
    return
  fi

  local dst_checksum
  dst_checksum=$(sha256 "$dst")

  if [[ "$src_checksum" == "$dst_checksum" ]]; then
    # No change needed
    return
  fi

  # File differs — check if locally modified
  if [[ -n "$state_key" ]]; then
    local stored_checksum
    stored_checksum=$(jq -r --arg key "$state_key" '.managed_skills[$key].checksum // ""' "$WORKSPACE/managed-state.json")

    if [[ -n "$stored_checksum" && "$dst_checksum" != "$stored_checksum" ]]; then
      if ! $FORCE; then
        echo "    SKIP:    $label (locally modified)"
        COUNT_SKIPPED=$((COUNT_SKIPPED + 1))
        return
      fi
    fi
  fi

  echo "    UPDATE:  $label"
  COUNT_UPDATED=$((COUNT_UPDATED + 1))
}

# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------
if $DRY_RUN; then
  echo "  Skills:"
  while IFS= read -r skill_name; do
    [[ -z "$skill_name" ]] && continue
    SKILL_SRC="$REPO_SKILLS/$skill_name/SKILL.md"
    SKILL_DST="$WORKSPACE/skills/managed/$skill_name/SKILL.md"
    compare_file "$SKILL_SRC" "$SKILL_DST" "skills/managed/$skill_name/SKILL.md" "$skill_name"

    # Also check other files in the skill directory
    if [[ -d "$REPO_SKILLS/$skill_name" ]]; then
      for src_file in "$REPO_SKILLS/$skill_name/"*; do
        [[ -f "$src_file" ]] || continue
        local_name=$(basename "$src_file")
        [[ "$local_name" == "SKILL.md" ]] && continue
        compare_file "$src_file" "$WORKSPACE/skills/managed/$skill_name/$local_name" "skills/managed/$skill_name/$local_name" ""
      done
    fi
  done <<< "$SKILLS_LIST"

  echo ""
  echo "  Identity:"
  if [[ -d "$REPO_IDENTITY" ]]; then
    for src_file in "$REPO_IDENTITY/"*.md; do
      [[ -f "$src_file" ]] || continue
      local_name=$(basename "$src_file")
      compare_file "$src_file" "$WORKSPACE/identity/managed/$local_name" "identity/managed/$local_name" ""
    done
  fi

  echo ""
  echo "  Summary: $COUNT_NEW new, $COUNT_UPDATED updated, $COUNT_SKIPPED skipped (locally modified)"
  echo ""
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 1: Snapshot BEFORE changes
# ---------------------------------------------------------------------------
BACKUP_DIR="$BULL_ROOT/.backups/feed/$TIMESTAMP"
echo "  [1/5] Creating backup snapshot..."
echo "        $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

# Backup managed skills
if [[ -d "$WORKSPACE/skills/managed" ]]; then
  cp -r "$WORKSPACE/skills/managed" "$BACKUP_DIR/skills-managed"
fi

# Backup managed identity
if [[ -d "$WORKSPACE/identity/managed" ]]; then
  cp -r "$WORKSPACE/identity/managed" "$BACKUP_DIR/identity-managed"
fi

# Backup managed-state.json
cp "$WORKSPACE/managed-state.json" "$BACKUP_DIR/managed-state.json"

# Backup IDENTITY.md
if [[ -f "$WORKSPACE/IDENTITY.md" ]]; then
  cp "$WORKSPACE/IDENTITY.md" "$BACKUP_DIR/IDENTITY.md"
fi

# ---------------------------------------------------------------------------
# Step 2: Update managed skills
# ---------------------------------------------------------------------------
echo "  [2/5] Updating managed skills..."

while IFS= read -r skill_name; do
  [[ -z "$skill_name" ]] && continue

  SKILL_SRC_DIR="$REPO_SKILLS/$skill_name"
  SKILL_DST_DIR="$WORKSPACE/skills/managed/$skill_name"

  if [[ ! -d "$SKILL_SRC_DIR" ]]; then
    echo "         WARNING: Skill '$skill_name' not found in repo, skipping" >&2
    continue
  fi

  SKILL_MD_SRC="$SKILL_SRC_DIR/SKILL.md"
  SKILL_MD_DST="$SKILL_DST_DIR/SKILL.md"

  if [[ ! -f "$SKILL_MD_SRC" ]]; then
    echo "         WARNING: SKILL.md not found for '$skill_name', skipping" >&2
    continue
  fi

  # New skill (not yet deployed)
  if [[ ! -d "$SKILL_DST_DIR" ]]; then
    mkdir -p "$SKILL_DST_DIR"
    cp -r "$SKILL_SRC_DIR/"* "$SKILL_DST_DIR/"
    echo "         NEW: $skill_name"
    COUNT_NEW=$((COUNT_NEW + 1))
    continue
  fi

  # Existing skill — check for local modifications
  if [[ -f "$SKILL_MD_DST" ]]; then
    dst_checksum=$(sha256 "$SKILL_MD_DST")
    src_checksum=$(sha256 "$SKILL_MD_SRC")

    # Already up to date
    if [[ "$src_checksum" == "$dst_checksum" ]]; then
      continue
    fi

    # Check if locally modified (dst differs from stored checksum)
    stored_checksum=$(jq -r --arg key "$skill_name" '.managed_skills[$key].checksum // ""' "$WORKSPACE/managed-state.json")

    if [[ -n "$stored_checksum" && "$dst_checksum" != "$stored_checksum" && "$FORCE" == false ]]; then
      echo "         SKIP: $skill_name (locally modified)"
      COUNT_SKIPPED=$((COUNT_SKIPPED + 1))

      # Mark as dirty in state
      TMP_STATE=$(mktemp)
      jq --arg key "$skill_name" '.managed_skills[$key].dirty = true' "$WORKSPACE/managed-state.json" > "$TMP_STATE"
      mv "$TMP_STATE" "$WORKSPACE/managed-state.json"
      continue
    fi
  fi

  # Copy all files from repo skill to workspace
  cp -r "$SKILL_SRC_DIR/"* "$SKILL_DST_DIR/"
  echo "         UPDATE: $skill_name"
  COUNT_UPDATED=$((COUNT_UPDATED + 1))

  # Update checksum in managed-state.json
  new_checksum=$(sha256 "$SKILL_MD_DST")
  TMP_STATE=$(mktemp)
  jq --arg key "$skill_name" \
     --arg ver "$VERSION" \
     --arg cs "$new_checksum" \
     --arg ts "$TIMESTAMP" \
     '.managed_skills[$key] = {"version": $ver, "checksum": $cs, "updated_at": $ts, "dirty": false}' \
     "$WORKSPACE/managed-state.json" > "$TMP_STATE"
  mv "$TMP_STATE" "$WORKSPACE/managed-state.json"
done <<< "$SKILLS_LIST"

# ---------------------------------------------------------------------------
# Step 3: Update managed identity files
# ---------------------------------------------------------------------------
echo "  [3/5] Updating managed identity files..."

if [[ -d "$REPO_IDENTITY" ]]; then
  mkdir -p "$WORKSPACE/identity/managed"

  for src_file in "$REPO_IDENTITY/"*.md; do
    [[ -f "$src_file" ]] || continue
    fname=$(basename "$src_file")
    dst_file="$WORKSPACE/identity/managed/$fname"

    if [[ ! -f "$dst_file" ]]; then
      cp "$src_file" "$dst_file"
      echo "         NEW: identity/managed/$fname"
      COUNT_NEW=$((COUNT_NEW + 1))
      continue
    fi

    src_checksum=$(sha256 "$src_file")
    dst_checksum=$(sha256 "$dst_file")

    # Already up to date
    if [[ "$src_checksum" == "$dst_checksum" ]]; then
      continue
    fi

    # For identity files, we don't have per-file state tracking,
    # so compare repo source with what was last deployed.
    # If force or file hasn't been locally modified, update it.
    if [[ "$FORCE" == false ]]; then
      # Check backup to see if file was locally modified
      backup_file="$BACKUP_DIR/identity-managed/$fname"
      if [[ -f "$backup_file" ]]; then
        backup_checksum=$(sha256 "$backup_file")
        # backup == current dst, but we need to check if dst differs from what repo had last time
        # Without per-file state, we use force for safety on identity files
        # In safe mode, always update identity (they are short, repo is source of truth)
      fi
    fi

    cp "$src_file" "$dst_file"
    echo "         UPDATE: identity/managed/$fname"
    COUNT_UPDATED=$((COUNT_UPDATED + 1))
  done
else
  echo "         WARNING: Identity region '$REGION' not found in repo" >&2
fi

# ---------------------------------------------------------------------------
# Step 4: Recompile IDENTITY.md
# ---------------------------------------------------------------------------
echo "  [4/5] Recompiling IDENTITY.md..."
{
  echo '<!-- AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY. Source: identity/managed/ + identity/local/ -->'
  echo ''
  for f in "$WORKSPACE/identity/managed/"*.md; do
    [[ -f "$f" ]] || continue
    cat "$f"
    echo ''
  done
  if ls "$WORKSPACE/identity/local/"*.md &>/dev/null; then
    echo ''
    echo '---'
    echo ''
    echo '## 本地補充資料'
    echo ''
    for f in "$WORKSPACE/identity/local/"*.md; do
      [[ -f "$f" ]] || continue
      cat "$f"
      echo ''
    done
  fi
} > "$WORKSPACE/IDENTITY.md"

# ---------------------------------------------------------------------------
# Step 5: Update managed-state.json metadata + run sanitize
# ---------------------------------------------------------------------------
echo "  [5/5] Updating managed-state.json..."

TMP_STATE=$(mktemp)
jq --arg ver "$VERSION" \
   --arg ts "$TIMESTAMP" \
   --arg backup "$BACKUP_DIR" \
   '.raise_a_bull_version = $ver |
    .skills_bundle_version = $ver |
    .last_feed_at = $ts |
    .last_backup_at = $ts |
    .last_backup_path = $backup' \
   "$WORKSPACE/managed-state.json" > "$TMP_STATE"
mv "$TMP_STATE" "$WORKSPACE/managed-state.json"

# Update checksums for new skills that were added
while IFS= read -r skill_name; do
  [[ -z "$skill_name" ]] && continue
  SKILL_MD="$WORKSPACE/skills/managed/$skill_name/SKILL.md"
  if [[ -f "$SKILL_MD" ]]; then
    existing=$(jq -r --arg key "$skill_name" '.managed_skills[$key] // empty' "$WORKSPACE/managed-state.json")
    if [[ -z "$existing" ]]; then
      new_checksum=$(sha256 "$SKILL_MD")
      TMP_STATE=$(mktemp)
      jq --arg key "$skill_name" \
         --arg ver "$VERSION" \
         --arg cs "$new_checksum" \
         --arg ts "$TIMESTAMP" \
         '.managed_skills[$key] = {"version": $ver, "checksum": $cs, "updated_at": $ts, "dirty": false}' \
         "$WORKSPACE/managed-state.json" > "$TMP_STATE"
      mv "$TMP_STATE" "$WORKSPACE/managed-state.json"
    fi
  fi
done <<< "$SKILLS_LIST"

# Pretty-print
TMP_STATE=$(mktemp)
jq '.' "$WORKSPACE/managed-state.json" > "$TMP_STATE" && mv "$TMP_STATE" "$WORKSPACE/managed-state.json"

# Run sanitize.sh on workspace skills
if [[ -x "$SCRIPT_DIR/sanitize.sh" ]]; then
  echo ""
  echo "  --- sanitize.sh ---"
  "$SCRIPT_DIR/sanitize.sh" "$WORKSPACE/skills" || true
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "  ============================================"
echo "  Feed complete!"
echo "  ============================================"
echo ""
echo "  Bull:       $INSTANCE_ID"
echo "  New:        $COUNT_NEW"
echo "  Updated:    $COUNT_UPDATED"
echo "  Skipped:    $COUNT_SKIPPED (locally modified)"
echo "  Backup:     $BACKUP_DIR"
echo ""

if [[ $COUNT_SKIPPED -gt 0 ]]; then
  echo "  TIP: Use --force to overwrite locally modified files."
  echo ""
fi
