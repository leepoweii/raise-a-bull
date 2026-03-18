#!/usr/bin/env bash
set -euo pipefail

# Raise a new bull (deploy a new OpenClaw instance)
# Usage: ./scripts/raise.sh --preset association --name "培力站助理" --port 18890
#        ./scripts/raise.sh --preset association --name "培力站助理" --port 18890 --native
#
# Default: Docker mode（推薦，隔離乾淨）
# --native: 直接跑 process（開發/debug 用）

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
PRESET=""
DISPLAY_NAME=""
PORT=18888
INSTANCE_ID=""
NATIVE=false
REGION="kinmen"
BULLS_DIR="$HOME/bulls"

# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------
usage() {
  cat <<'EOF'
raise.sh — Raise a new bull (OpenClaw instance)

Usage:
  ./scripts/raise.sh --preset <preset> --name <name> [options]

Required:
  --preset <name>       Preset to use (bar, association, shop, office)
  --name <name>         Display name for the bull (e.g. "培力站助理")

Options:
  --port <port>         Gateway port (default: 18888)
  --instance-id <id>    Instance ID in kebab-case (auto-generated from --name if ASCII)
  --native              Use native mode instead of Docker
  --help                Show this help message

Examples:
  ./scripts/raise.sh --preset association --name "peili-station" --port 18890
  ./scripts/raise.sh --preset bar --name "dream-bar" --port 18891 --native
  ./scripts/raise.sh --preset association --name "培力站" --instance-id peili-station
EOF
  exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
if [[ $# -eq 0 ]]; then
  usage
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preset)    PRESET="$2"; shift 2 ;;
    --name)      DISPLAY_NAME="$2"; shift 2 ;;
    --port)      PORT="$2"; shift 2 ;;
    --instance-id) INSTANCE_ID="$2"; shift 2 ;;
    --native)    NATIVE=true; shift ;;
    --help|-h)   usage ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      echo "Run with --help for usage." >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
if [[ -z "$PRESET" ]]; then
  echo "ERROR: --preset is required" >&2
  exit 1
fi

if [[ -z "$DISPLAY_NAME" ]]; then
  echo "ERROR: --name is required" >&2
  exit 1
fi

# Validate preset exists
PRESET_FILE="$REPO_ROOT/presets/$PRESET.json"
if [[ ! -f "$PRESET_FILE" ]]; then
  echo "ERROR: Preset '$PRESET' not found at $PRESET_FILE" >&2
  echo "Available presets:" >&2
  ls "$REPO_ROOT/presets/"*.json 2>/dev/null | xargs -I{} basename {} .json | sed 's/^/  /' >&2
  exit 1
fi

# Auto-generate instance-id from name if not provided
if [[ -z "$INSTANCE_ID" ]]; then
  # Check if name contains non-ASCII characters
  if echo "$DISPLAY_NAME" | LC_ALL=C grep -q '[^[:print:][:space:]]' 2>/dev/null; then
    echo "ERROR: --name contains non-ASCII characters. Please provide --instance-id explicitly." >&2
    echo "  e.g. --instance-id peili-station" >&2
    exit 1
  fi
  # Convert to kebab-case: lowercase, replace spaces/underscores with hyphens, strip non-alnum
  INSTANCE_ID=$(echo "$DISPLAY_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[_ ]/-/g' | sed 's/[^a-z0-9-]//g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
fi

# Validate instance-id format
if ! [[ "$INSTANCE_ID" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
  echo "ERROR: Instance ID '$INSTANCE_ID' is invalid. Must be kebab-case (e.g. 'peili-station')." >&2
  exit 1
fi

# Validate port is a number
if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --port must be a number, got '$PORT'" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Read preset data
# ---------------------------------------------------------------------------
SKILLS_JSON=$(jq -r '.skills // []' "$PRESET_FILE")
SKILLS_LIST=$(echo "$SKILLS_JSON" | jq -r '.[]')
CHANNELS_JSON=$(jq -c '.channels // []' "$PRESET_FILE")
INTEGRATIONS_JSON=$(jq -c '.integrations // {}' "$PRESET_FILE")

# Read version
VERSION=$(cat "$REPO_ROOT/VERSION" 2>/dev/null | tr -d '[:space:]' || echo "0.0.0")

# Timestamp
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

echo ""
echo "  raise-a-bull — raising a new bull"
echo ""
echo "  Instance:  $INSTANCE_ID"
echo "  Name:      $DISPLAY_NAME"
echo "  Preset:    $PRESET"
echo "  Port:      $PORT"
echo "  Mode:      $(if $NATIVE; then echo 'native'; else echo 'docker'; fi)"
echo ""

# ---------------------------------------------------------------------------
# Step 3: Determine bull directory
# ---------------------------------------------------------------------------
BULL_DIR="$BULLS_DIR/$INSTANCE_ID"
WORKSPACE="$BULL_DIR/workspace"

if [[ -d "$BULL_DIR" ]]; then
  echo "ERROR: Bull directory already exists: $BULL_DIR" >&2
  echo "If you want to re-raise, remove it first: rm -rf $BULL_DIR" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 4: Create workspace directories
# ---------------------------------------------------------------------------
echo "  [1/12] Creating workspace directories..."
mkdir -p "$WORKSPACE/skills/managed"
mkdir -p "$WORKSPACE/skills/local"
mkdir -p "$WORKSPACE/identity/managed"
mkdir -p "$WORKSPACE/identity/local"
mkdir -p "$WORKSPACE/secrets"
mkdir -p "$WORKSPACE/memory"

# Restrict secrets directory permissions
chmod 700 "$WORKSPACE/secrets"

# ---------------------------------------------------------------------------
# Step 5: Copy skills from repo based on preset
# ---------------------------------------------------------------------------
echo "  [2/12] Installing skills from preset '$PRESET'..."
SKILL_COUNT=0
while IFS= read -r skill_name; do
  [[ -z "$skill_name" ]] && continue
  SKILL_SRC="$REPO_ROOT/skills/$skill_name"
  if [[ -d "$SKILL_SRC" ]]; then
    cp -r "$SKILL_SRC" "$WORKSPACE/skills/managed/$skill_name"
    SKILL_COUNT=$((SKILL_COUNT + 1))
  else
    echo "  WARNING: Skill '$skill_name' not found in repo, skipping" >&2
  fi
done <<< "$SKILLS_LIST"
echo "           $SKILL_COUNT skill(s) installed"

# ---------------------------------------------------------------------------
# Step 6: Copy identity region files
# ---------------------------------------------------------------------------
echo "  [3/12] Copying identity files (region: $REGION)..."
IDENTITY_SRC="$REPO_ROOT/identity/regions/$REGION"
if [[ -d "$IDENTITY_SRC" ]]; then
  cp -r "$IDENTITY_SRC/"* "$WORKSPACE/identity/managed/" 2>/dev/null || true
else
  echo "  WARNING: Identity region '$REGION' not found, skipping" >&2
fi

# ---------------------------------------------------------------------------
# Step 7: Compile IDENTITY.md
# ---------------------------------------------------------------------------
echo "  [4/12] Compiling IDENTITY.md..."
{
  echo '<!-- AUTO-GENERATED FILE - DO NOT EDIT DIRECTLY. Source: identity/managed/ + identity/local/ -->'
  echo ''
  # Concatenate all managed identity files
  for f in "$WORKSPACE/identity/managed/"*.md; do
    [[ -f "$f" ]] || continue
    cat "$f"
    echo ''
  done
  # identity/local/ is empty at first raise, but include if files exist
  for f in "$WORKSPACE/identity/local/"*.md; do
    [[ -f "$f" ]] || continue
    cat "$f"
    echo ''
  done
} > "$WORKSPACE/IDENTITY.md"

# ---------------------------------------------------------------------------
# Step 8: Generate SOUL.md from template
# ---------------------------------------------------------------------------
echo "  [5/12] Generating SOUL.md..."
SOUL_TEMPLATE="$REPO_ROOT/identity/templates/SOUL.md.template"
if [[ -f "$SOUL_TEMPLATE" ]]; then
  # Build skills bullet list
  SKILLS_BULLET_LIST=""
  while IFS= read -r skill_name; do
    [[ -z "$skill_name" ]] && continue
    SKILLS_BULLET_LIST="${SKILLS_BULLET_LIST}- ${skill_name}\n"
  done <<< "$SKILLS_LIST"
  # Remove trailing \n
  SKILLS_BULLET_LIST="${SKILLS_BULLET_LIST%\\n}"

  # Use sed for template substitution; write to temp file to handle multi-line
  cp "$SOUL_TEMPLATE" "$WORKSPACE/SOUL.md"
  # Simple replacements first
  sed -i.bak "s|{{DISPLAY_NAME}}|${DISPLAY_NAME}|g" "$WORKSPACE/SOUL.md"
  sed -i.bak "s|{{ORG_NAME}}|${DISPLAY_NAME}|g" "$WORKSPACE/SOUL.md"
  sed -i.bak "s|{{ORG_LOCATION}}|金門|g" "$WORKSPACE/SOUL.md"
  # For skills list, use printf to expand \n then replace
  SKILLS_EXPANDED=$(printf '%b' "$SKILLS_BULLET_LIST")
  # Use a temp file approach for multiline replacement
  python3 -c "
import sys
with open(sys.argv[1], 'r') as f:
    content = f.read()
content = content.replace('{{SKILLS_LIST}}', sys.argv[2])
with open(sys.argv[1], 'w') as f:
    f.write(content)
" "$WORKSPACE/SOUL.md" "$SKILLS_EXPANDED"
  rm -f "$WORKSPACE/SOUL.md.bak"
else
  echo "  WARNING: SOUL.md template not found, skipping" >&2
fi

# ---------------------------------------------------------------------------
# Step 9: Generate TOOLS.md from template
# ---------------------------------------------------------------------------
echo "  [6/12] Generating TOOLS.md..."
TOOLS_TEMPLATE="$REPO_ROOT/identity/templates/TOOLS.md.template"
if [[ -f "$TOOLS_TEMPLATE" ]]; then
  # Build integrations list from preset
  INTEGRATIONS_BULLET_LIST=""
  while IFS='=' read -r int_name int_val; do
    [[ -z "$int_name" ]] && continue
    if [[ "$int_val" == "true" ]]; then
      INTEGRATIONS_BULLET_LIST="${INTEGRATIONS_BULLET_LIST}- ${int_name} (啟用)
"
    else
      INTEGRATIONS_BULLET_LIST="${INTEGRATIONS_BULLET_LIST}- ${int_name} (${int_val})
"
    fi
  done < <(jq -r '.integrations // {} | to_entries[] | "\(.key)=\(.value)"' "$PRESET_FILE" 2>/dev/null || true)

  if [[ -z "$INTEGRATIONS_BULLET_LIST" ]]; then
    INTEGRATIONS_BULLET_LIST="- (無整合服務)"
  fi

  cp "$TOOLS_TEMPLATE" "$WORKSPACE/TOOLS.md"
  sed -i.bak "s|{{GATEWAY_PORT}}|${PORT}|g" "$WORKSPACE/TOOLS.md"
  sed -i.bak "s|{{REGION}}|${REGION}|g" "$WORKSPACE/TOOLS.md"
  # Multiline replacement for integrations list
  INTEGRATIONS_EXPANDED=$(printf '%b' "${INTEGRATIONS_BULLET_LIST%\\n}")
  python3 -c "
import sys
with open(sys.argv[1], 'r') as f:
    content = f.read()
content = content.replace('{{INTEGRATIONS_LIST}}', sys.argv[2])
with open(sys.argv[1], 'w') as f:
    f.write(content)
" "$WORKSPACE/TOOLS.md" "$INTEGRATIONS_EXPANDED"
  rm -f "$WORKSPACE/TOOLS.md.bak"
else
  echo "  WARNING: TOOLS.md template not found, skipping" >&2
fi

# ---------------------------------------------------------------------------
# Step 10: Generate bull.json
# ---------------------------------------------------------------------------
echo "  [7/12] Generating bull.json..."

# Build skills_installed array
SKILLS_INSTALLED_JSON=$(echo "$SKILLS_JSON" | jq -c '.')

cat > "$WORKSPACE/bull.json" <<EOJSON
{
  "instance_id": "$INSTANCE_ID",
  "display_name": $(echo "$DISPLAY_NAME" | jq -Rs '.[:length-1]'),
  "preset": "$PRESET",
  "region": "$REGION",
  "created_at": "$TIMESTAMP",
  "workspace_root": "$WORKSPACE",
  "raise_a_bull_version": "$VERSION",
  "skills_version": "$VERSION",
  "skills_installed": $SKILLS_INSTALLED_JSON,
  "channels": $CHANNELS_JSON,
  "managed_paths": ["skills/managed/", "identity/managed/", "managed-state.json", "IDENTITY.md"],
  "unmanaged_paths": ["SOUL.md", "memory/", "skills/local/", "identity/local/", "secrets/"]
}
EOJSON

# ---------------------------------------------------------------------------
# Step 11: Generate params.json
# ---------------------------------------------------------------------------
echo "  [8/12] Generating params.json..."

# Check if preset has weather integration for defaults
HAS_CWA=$(jq -r '.integrations.cwa // false' "$PRESET_FILE")
HAS_CALENDAR=$(jq -r '.integrations.google_calendar // false' "$PRESET_FILE")
HAS_TASKS=$(jq -r '.integrations.google_tasks // false' "$PRESET_FILE")

PARAMS_JSON="{
  \"brand\": {
    \"name\": $(echo "$DISPLAY_NAME" | jq -Rs '.[:length-1]'),
    \"font_cn\": \"Noto Sans TC\",
    \"location\": \"金門\"
  }"

if [[ "$HAS_CWA" != "false" ]]; then
  PARAMS_JSON="$PARAMS_JSON,
  \"weather\": {
    \"default_location\": \"金城鎮\",
    \"dataset\": \"F-D0047-085\"
  }"
fi

if [[ "$HAS_CALENDAR" != "false" ]]; then
  PARAMS_JSON="$PARAMS_JSON,
  \"calendar\": {
    \"default_calendar\": \"primary\",
    \"timezone\": \"Asia/Taipei\"
  }"
fi

if [[ "$HAS_TASKS" != "false" ]]; then
  PARAMS_JSON="$PARAMS_JSON,
  \"tasks\": {}"
fi

PARAMS_JSON="$PARAMS_JSON,
  \"timezone\": \"Asia/Taipei\"
}"

echo "$PARAMS_JSON" | jq '.' > "$WORKSPACE/params.json"

# ---------------------------------------------------------------------------
# Step 12: Generate managed-state.json
# ---------------------------------------------------------------------------
echo "  [9/12] Generating managed-state.json..."

# Build managed_skills object with checksums
MANAGED_SKILLS_JSON="{}"
while IFS= read -r skill_name; do
  [[ -z "$skill_name" ]] && continue
  SKILL_MD="$WORKSPACE/skills/managed/$skill_name/SKILL.md"
  if [[ -f "$SKILL_MD" ]]; then
    # Compute sha256 checksum (works on both macOS and Linux)
    if command -v sha256sum &>/dev/null; then
      CHECKSUM=$(sha256sum "$SKILL_MD" | cut -d' ' -f1)
    elif command -v shasum &>/dev/null; then
      CHECKSUM=$(shasum -a 256 "$SKILL_MD" | cut -d' ' -f1)
    else
      CHECKSUM="0000000000000000000000000000000000000000000000000000000000000000"
    fi
    MANAGED_SKILLS_JSON=$(echo "$MANAGED_SKILLS_JSON" | jq \
      --arg name "$skill_name" \
      --arg ver "$VERSION" \
      --arg cs "$CHECKSUM" \
      --arg ts "$TIMESTAMP" \
      '. + {($name): {"version": $ver, "checksum": $cs, "updated_at": $ts, "dirty": false}}')
  fi
done <<< "$SKILLS_LIST"

cat > "$WORKSPACE/managed-state.json" <<EOJSON
{
  "raise_a_bull_version": "$VERSION",
  "skills_bundle_version": "$VERSION",
  "last_raise_at": "$TIMESTAMP",
  "last_feed_at": null,
  "last_backup_at": null,
  "managed_skills": $MANAGED_SKILLS_JSON
}
EOJSON

# Pretty-print
TMP_STATE=$(mktemp)
jq '.' "$WORKSPACE/managed-state.json" > "$TMP_STATE" && mv "$TMP_STATE" "$WORKSPACE/managed-state.json"

# ---------------------------------------------------------------------------
# Step 13: Copy .env.example
# ---------------------------------------------------------------------------
echo "  [10/12] Copying .env.example..."
cp "$REPO_ROOT/templates/.env.example" "$WORKSPACE/secrets/.env.example"

# ---------------------------------------------------------------------------
# Step 14-17: Docker or Native mode
# ---------------------------------------------------------------------------
if [[ "$NATIVE" == false ]]; then
  echo "  [11/12] Setting up Docker deployment..."

  # Copy Dockerfile
  cp "$REPO_ROOT/templates/Dockerfile" "$BULL_DIR/Dockerfile"

  # Generate docker-compose.yml from template
  COMPOSE_TEMPLATE="$REPO_ROOT/templates/docker-compose.yml.template"
  if [[ -f "$COMPOSE_TEMPLATE" ]]; then
    python3 -c "
import sys
with open(sys.argv[1], 'r') as f:
    content = f.read()
content = content.replace('{{DISPLAY_NAME}}', sys.argv[2])
content = content.replace('{{INSTANCE_ID}}', sys.argv[3])
content = content.replace('{{PORT}}', sys.argv[4])
content = content.replace('{{TIMESTAMP}}', sys.argv[5])
with open(sys.argv[6], 'w') as f:
    f.write(content)
" "$COMPOSE_TEMPLATE" "$DISPLAY_NAME" "$INSTANCE_ID" "$PORT" "$TIMESTAMP" "$BULL_DIR/docker-compose.yml"
  fi

  # Verify Docker installed
  if ! command -v docker &>/dev/null; then
    echo "  WARNING: Docker not found. Install Docker before running docker compose." >&2
  fi

  # Check target port not in use
  PORT_IN_USE=false
  if command -v lsof &>/dev/null; then
    if lsof -i ":$PORT" -sTCP:LISTEN &>/dev/null 2>&1; then
      PORT_IN_USE=true
    fi
  elif command -v ss &>/dev/null; then
    if ss -tlnp "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
      PORT_IN_USE=true
    fi
  fi
  if [[ "$PORT_IN_USE" == true ]]; then
    echo "  WARNING: Port $PORT is already in use!" >&2
  fi
else
  echo "  [11/12] Native mode — skipping Docker setup"
fi

# ---------------------------------------------------------------------------
# Step 18-19: Run doctor.sh and sanitize.sh
# ---------------------------------------------------------------------------
echo "  [12/12] Running health checks..."

# Run sanitize.sh on workspace skills
if [[ -x "$SCRIPT_DIR/sanitize.sh" ]]; then
  echo ""
  echo "  --- sanitize.sh ---"
  "$SCRIPT_DIR/sanitize.sh" "$WORKSPACE/skills" || true
fi

# Run doctor.sh on the bull
if [[ -x "$SCRIPT_DIR/doctor.sh" ]]; then
  echo ""
  echo "  --- doctor.sh ---"
  "$SCRIPT_DIR/doctor.sh" "$BULL_DIR" || true
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "  ============================================"
echo "  Bull raised successfully!"
echo "  ============================================"
echo ""
echo "  Instance:   $INSTANCE_ID"
echo "  Name:       $DISPLAY_NAME"
echo "  Preset:     $PRESET"
echo "  Port:       $PORT"
echo "  Location:   $BULL_DIR"
echo "  Workspace:  $WORKSPACE"
echo ""

if [[ "$NATIVE" == false ]]; then
  echo "  Next steps:"
  echo "  1. 填好 API keys:"
  echo "     cp $WORKSPACE/secrets/.env.example $WORKSPACE/secrets/provider.env"
  echo "     \$EDITOR $WORKSPACE/secrets/provider.env"
  echo ""
  echo "  2. 啟動服務:"
  echo "     cd $BULL_DIR && docker compose up -d"
  echo ""
else
  echo "  Next steps:"
  echo "  1. 填好 API keys:"
  echo "     cp $WORKSPACE/secrets/.env.example $WORKSPACE/secrets/provider.env"
  echo "     \$EDITOR $WORKSPACE/secrets/provider.env"
  echo ""
  echo "  2. 啟動服務:"
  echo "     openclaw gateway --workspace $WORKSPACE --port $PORT"
  echo ""
fi
