#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/doctor.sh [--json] [bull-root-path]
# Note: accepts bull root (~/bulls/X/), derives workspace as ~/bulls/X/workspace/
# --json: structured output for management UI / automation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
JSON_OUTPUT=false
BULL_ROOT=""

for arg in "$@"; do
  case "$arg" in
    --json) JSON_OUTPUT=true ;;
    *) BULL_ROOT="$arg" ;;
  esac
done

if [[ -z "$BULL_ROOT" ]]; then
  echo "Usage: ./scripts/doctor.sh [--json] <bull-root-path>" >&2
  echo "  e.g. ./scripts/doctor.sh ~/bulls/peili-station" >&2
  exit 1
fi

# Resolve and validate bull root
BULL_ROOT="$(cd "$BULL_ROOT" 2>/dev/null && pwd)" || {
  echo "ERROR: Bull root path does not exist: $BULL_ROOT" >&2
  exit 1
}
WORKSPACE="$BULL_ROOT/workspace"

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
declare -a CHECK_NAMES CHECK_STATUSES CHECK_DETAILS
OK_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

record() {
  local id="$1" name="$2" status="$3" details="${4:-}"
  CHECK_NAMES+=("$name")
  CHECK_STATUSES+=("$status")
  CHECK_DETAILS+=("$details")
  case "$status" in
    OK)   OK_COUNT=$((OK_COUNT + 1)) ;;
    WARN) WARN_COUNT=$((WARN_COUNT + 1)) ;;
    FAIL) FAIL_COUNT=$((FAIL_COUNT + 1)) ;;
  esac
}

# ---------------------------------------------------------------------------
# Check 1: Workspace structure
# ---------------------------------------------------------------------------
check_workspace_structure() {
  local required_files=("bull.json" "params.json")
  local required_dirs=("secrets" "skills/managed" "skills/local" "memory" "identity/managed" "identity/local")
  local missing=()

  for f in "${required_files[@]}"; do
    [[ -f "$WORKSPACE/$f" ]] || missing+=("$f")
  done
  for d in "${required_dirs[@]}"; do
    [[ -d "$WORKSPACE/$d" ]] || missing+=("$d/")
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    record 1 "workspace_structure" "OK" ""
  else
    record 1 "workspace_structure" "FAIL" "missing: ${missing[*]}"
  fi
}

# ---------------------------------------------------------------------------
# Check 2: File permissions
# ---------------------------------------------------------------------------
check_permissions() {
  local issues=()
  local status="OK"

  if [[ ! -w "$WORKSPACE" ]]; then
    issues+=("workspace not writable")
    status="FAIL"
  fi

  if [[ -d "$WORKSPACE/secrets" ]]; then
    # Check if secrets/ is world-readable (o+r)
    local perms
    if [[ "$(uname)" == "Darwin" ]]; then
      perms=$(stat -f '%Lp' "$WORKSPACE/secrets" 2>/dev/null || echo "000")
    else
      perms=$(stat -c '%a' "$WORKSPACE/secrets" 2>/dev/null || echo "000")
    fi
    # Check if "others" bits include read (last digit has 4 set)
    local other_bits=$((perms % 10))
    if (( other_bits & 4 )); then
      issues+=("secrets/ is world-readable (mode $perms)")
      [[ "$status" != "FAIL" ]] && status="WARN"
    fi
  fi

  record 2 "file_permissions" "$status" "$(IFS='; '; echo "${issues[*]+"${issues[*]}"}")"
}

# ---------------------------------------------------------------------------
# Check 3: bull.json schema validation
# ---------------------------------------------------------------------------
check_bull_json() {
  local bull_json="$WORKSPACE/bull.json"
  if [[ ! -f "$bull_json" ]]; then
    record 3 "bull_json_validation" "FAIL" "bull.json not found"
    return
  fi

  # Valid JSON?
  if ! jq empty "$bull_json" 2>/dev/null; then
    record 3 "bull_json_validation" "FAIL" "invalid JSON"
    return
  fi

  local required_fields=("instance_id" "preset" "region" "created_at" "workspace_root" "display_name")
  local missing=()

  for field in "${required_fields[@]}"; do
    local val
    val=$(jq -r --arg f "$field" '.[$f] // empty' "$bull_json" 2>/dev/null)
    if [[ -z "$val" ]]; then
      missing+=("$field")
    fi
  done

  # Validate preset value
  local preset
  preset=$(jq -r '.preset // empty' "$bull_json" 2>/dev/null)
  if [[ -n "$preset" ]] && ! [[ "$preset" =~ ^(bar|association|shop|office)$ ]]; then
    missing+=("preset invalid: $preset")
  fi

  # Validate instance_id format
  local iid
  iid=$(jq -r '.instance_id // empty' "$bull_json" 2>/dev/null)
  if [[ -n "$iid" ]] && ! [[ "$iid" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
    missing+=("instance_id format invalid")
  fi

  if [[ ${#missing[@]} -eq 0 ]]; then
    record 3 "bull_json_validation" "OK" ""
  else
    record 3 "bull_json_validation" "FAIL" "${missing[*]}"
  fi
}

# ---------------------------------------------------------------------------
# Check 4: params.json schema validation
# ---------------------------------------------------------------------------
check_params_json() {
  local params_json="$WORKSPACE/params.json"
  if [[ ! -f "$params_json" ]]; then
    record 4 "params_json_validation" "FAIL" "params.json not found"
    return
  fi

  if ! jq empty "$params_json" 2>/dev/null; then
    record 4 "params_json_validation" "FAIL" "invalid JSON"
    return
  fi

  local issues=()
  local status="OK"

  # Check brand object and brand.name (required)
  local brand_name
  brand_name=$(jq -r '.brand.name // empty' "$params_json" 2>/dev/null)
  if [[ -z "$brand_name" ]]; then
    issues+=("missing brand.name")
    status="FAIL"
  fi

  # Check timezone (warn if missing, defaults at runtime)
  local tz
  tz=$(jq -r '.timezone // empty' "$params_json" 2>/dev/null)
  if [[ -z "$tz" ]]; then
    issues+=("missing timezone")
    [[ "$status" == "OK" ]] && status="WARN"
  fi

  # Validate optional color fields if present
  for color_field in "brand.primary_color" "brand.accent_color"; do
    local color_val
    color_val=$(jq -r ".$color_field // empty" "$params_json" 2>/dev/null)
    if [[ -n "$color_val" ]] && ! [[ "$color_val" =~ ^#[0-9A-Fa-f]{6}$ ]]; then
      issues+=("$color_field invalid: $color_val")
      [[ "$status" == "OK" ]] && status="WARN"
    fi
  done

  # Warn about unset env var references in backend.url
  local backend_url
  backend_url=$(jq -r '.backend.url // empty' "$params_json" 2>/dev/null)
  if [[ -n "$backend_url" ]] && [[ "$backend_url" =~ \$\{([A-Z_]+)\} ]]; then
    local env_var="${BASH_REMATCH[1]}"
    if [[ -z "${!env_var:-}" ]]; then
      issues+=("env var \$$env_var not set")
      [[ "$status" == "OK" ]] && status="WARN"
    fi
  fi

  record 4 "params_json_validation" "$status" "$(IFS='; '; echo "${issues[*]+"${issues[*]}"}")"
}

# ---------------------------------------------------------------------------
# Check 5: managed-state.json consistency
# ---------------------------------------------------------------------------
check_managed_state() {
  local state_json="$WORKSPACE/managed-state.json"
  if [[ ! -f "$state_json" ]]; then
    record 5 "managed_state_json" "WARN" "managed-state.json not found"
    return
  fi

  if ! jq empty "$state_json" 2>/dev/null; then
    record 5 "managed_state_json" "FAIL" "invalid JSON"
    return
  fi

  local issues=()
  local status="OK"

  # Required fields
  for field in "raise_a_bull_version" "last_raise_at" "managed_skills"; do
    local val
    val=$(jq -r --arg f "$field" '.[$f] // empty' "$state_json" 2>/dev/null)
    if [[ -z "$val" ]]; then
      issues+=("missing $field")
      status="WARN"
    fi
  done

  # Check managed_skills keys match disk directories
  local skill_keys
  skill_keys=$(jq -r '.managed_skills // {} | keys[]' "$state_json" 2>/dev/null || true)
  if [[ -n "$skill_keys" && -d "$WORKSPACE/skills/managed" ]]; then
    while IFS= read -r sk; do
      if [[ ! -d "$WORKSPACE/skills/managed/$sk" ]]; then
        issues+=("skill '$sk' in state but not on disk")
        [[ "$status" == "OK" ]] && status="WARN"
      fi
    done <<< "$skill_keys"

    # Check disk dirs not in state
    if [[ -d "$WORKSPACE/skills/managed" ]]; then
      for dir in "$WORKSPACE/skills/managed"/*/; do
        [[ -d "$dir" ]] || continue
        local dirname
        dirname=$(basename "$dir")
        if ! echo "$skill_keys" | grep -qx "$dirname"; then
          issues+=("skill '$dirname' on disk but not in state")
          [[ "$status" == "OK" ]] && status="WARN"
        fi
      done
    fi
  fi

  record 5 "managed_state_json" "$status" "$(IFS='; '; echo "${issues[*]+"${issues[*]}"}")"
}

# ---------------------------------------------------------------------------
# Check 6: Managed skills integrity
# ---------------------------------------------------------------------------
check_managed_skills() {
  local managed_dir="$WORKSPACE/skills/managed"
  if [[ ! -d "$managed_dir" ]]; then
    record 6 "managed_skills" "FAIL" "skills/managed/ not found"
    return
  fi

  local issues=()
  local status="OK"
  local has_skills=false

  for dir in "$managed_dir"/*/; do
    [[ -d "$dir" ]] || continue
    has_skills=true
    local skill_name
    skill_name=$(basename "$dir")

    # Each skill must have SKILL.md
    if [[ ! -f "$dir/SKILL.md" ]]; then
      issues+=("$skill_name missing SKILL.md")
      status="FAIL"
    fi
  done

  # Check if skill dirs exist in local/ too (confusion)
  if [[ -d "$WORKSPACE/skills/local" ]]; then
    for dir in "$managed_dir"/*/; do
      [[ -d "$dir" ]] || continue
      local skill_name
      skill_name=$(basename "$dir")
      if [[ -d "$WORKSPACE/skills/local/$skill_name" ]]; then
        issues+=("$skill_name exists in both managed/ and local/")
        [[ "$status" == "OK" ]] && status="WARN"
      fi
    done
  fi

  if [[ "$has_skills" == false ]]; then
    issues+=("no managed skills installed")
    [[ "$status" == "OK" ]] && status="WARN"
  fi

  record 6 "managed_skills" "$status" "$(IFS='; '; echo "${issues[*]+"${issues[*]}"}")"
}

# ---------------------------------------------------------------------------
# Check 7: Secrets / provider readiness
# ---------------------------------------------------------------------------
check_secrets() {
  local bull_json="$WORKSPACE/bull.json"
  if [[ ! -f "$bull_json" ]] || ! jq empty "$bull_json" 2>/dev/null; then
    record 7 "secrets_readiness" "WARN" "cannot read bull.json for preset info"
    return
  fi

  local preset
  preset=$(jq -r '.preset // empty' "$bull_json" 2>/dev/null)
  if [[ -z "$preset" ]]; then
    record 7 "secrets_readiness" "WARN" "no preset defined"
    return
  fi

  local preset_file="$REPO_ROOT/presets/$preset.json"
  if [[ ! -f "$preset_file" ]]; then
    record 7 "secrets_readiness" "WARN" "preset file not found: $preset.json"
    return
  fi

  local issues=()
  local status="OK"

  # Map integration names to expected secret files or env vars
  local integrations
  integrations=$(jq -r '.integrations // {} | to_entries[] | "\(.key)=\(.value)"' "$preset_file" 2>/dev/null || true)

  while IFS='=' read -r integration_name requirement; do
    [[ -z "$integration_name" ]] && continue

    local secret_missing=false
    case "$integration_name" in
      cwa)
        # CWA weather API key
        if [[ ! -f "$WORKSPACE/secrets/cwa_api_key" ]] && [[ -z "${CWA_API_KEY:-}" ]]; then
          secret_missing=true
        fi
        ;;
      google_calendar|google_tasks|gmail)
        # Google service credentials
        if [[ ! -f "$WORKSPACE/secrets/google_credentials.json" ]] && [[ -z "${GOOGLE_CREDENTIALS:-}" ]]; then
          secret_missing=true
        fi
        ;;
    esac

    if [[ "$secret_missing" == true ]]; then
      if [[ "$requirement" == "true" ]]; then
        issues+=("$integration_name required but secret not found")
        status="FAIL"
      else
        issues+=("$integration_name optional, secret not found")
        [[ "$status" == "OK" ]] && status="WARN"
      fi
    fi
  done <<< "$integrations"

  record 7 "secrets_readiness" "$status" "$(IFS='; '; echo "${issues[*]+"${issues[*]}"}")"
}

# ---------------------------------------------------------------------------
# Check 8: OpenClaw / Docker availability
# ---------------------------------------------------------------------------
check_runtime() {
  local issues=()
  local status="OK"

  if [[ -f "$BULL_ROOT/docker-compose.yml" ]] || [[ -f "$BULL_ROOT/docker-compose.yaml" ]]; then
    # Docker mode
    if ! command -v docker &>/dev/null; then
      issues+=("docker not found in PATH")
      status="FAIL"
    elif ! docker compose ps --filter "status=running" 2>/dev/null | grep -q "running\|Up" 2>/dev/null; then
      # Try docker-compose (v1) fallback
      if command -v docker-compose &>/dev/null; then
        if ! docker-compose -f "$BULL_ROOT/docker-compose.yml" ps 2>/dev/null | grep -q "Up" 2>/dev/null; then
          issues+=("containers not running")
          status="FAIL"
        fi
      else
        issues+=("containers not running or docker compose unavailable")
        status="FAIL"
      fi
    fi
  else
    # Native mode
    if command -v openclaw &>/dev/null; then
      local version
      version=$(openclaw --version 2>/dev/null || echo "unknown")
      issues+=("openclaw $version")
    else
      issues+=("openclaw not in PATH, no docker-compose.yml found")
      status="FAIL"
    fi
  fi

  record 8 "runtime_availability" "$status" "$(IFS='; '; echo "${issues[*]+"${issues[*]}"}")"
}

# ---------------------------------------------------------------------------
# Check 9: Port / network availability
# ---------------------------------------------------------------------------
check_port() {
  local issues=()
  local status="OK"
  local port=""

  # Try to read port from docker-compose.yml
  if [[ -f "$BULL_ROOT/docker-compose.yml" ]]; then
    port=$(grep -oP '"\K\d+(?=:\d+")' "$BULL_ROOT/docker-compose.yml" 2>/dev/null | head -1 || true)
  fi

  # Fallback: read from bull.json
  if [[ -z "$port" && -f "$WORKSPACE/bull.json" ]]; then
    port=$(jq -r '.port // empty' "$WORKSPACE/bull.json" 2>/dev/null || true)
  fi

  if [[ -z "$port" ]]; then
    issues+=("no port configured")
    status="WARN"
  else
    # Check if port is in use
    local in_use=false
    if command -v lsof &>/dev/null; then
      if lsof -i ":$port" -sTCP:LISTEN &>/dev/null; then
        in_use=true
      fi
    elif command -v ss &>/dev/null; then
      if ss -tlnp "sport = :$port" 2>/dev/null | grep -q LISTEN; then
        in_use=true
      fi
    fi

    if [[ "$in_use" == true ]]; then
      issues+=("port $port already in use")
      status="FAIL"
    fi
  fi

  # Check webhook URL
  if [[ -f "$WORKSPACE/bull.json" ]]; then
    local webhook
    webhook=$(jq -r '.webhook_url // empty' "$WORKSPACE/bull.json" 2>/dev/null || true)
    if [[ -z "$webhook" ]]; then
      issues+=("webhook URL not set")
      [[ "$status" == "OK" ]] && status="WARN"
    fi
  fi

  record 9 "port_availability" "$status" "$(IFS='; '; echo "${issues[*]+"${issues[*]}"}")"
}

# ---------------------------------------------------------------------------
# Check 10: Backup / sanitize / feed readiness
# ---------------------------------------------------------------------------
check_ops_readiness() {
  local issues=()
  local status="OK"

  # sanitize.sh executable
  if [[ -x "$REPO_ROOT/scripts/sanitize.sh" ]]; then
    : # ok
  else
    issues+=("sanitize.sh not executable")
    [[ "$status" == "OK" ]] && status="WARN"
  fi

  # backup.sh executable
  if [[ -x "$REPO_ROOT/scripts/backup.sh" ]]; then
    : # ok
  elif [[ -f "$REPO_ROOT/scripts/backup.sh" ]]; then
    issues+=("backup.sh not executable")
    [[ "$status" == "OK" ]] && status="WARN"
  else
    issues+=("backup.sh not found")
    [[ "$status" == "OK" ]] && status="WARN"
  fi

  # Check last backup from managed-state.json
  if [[ -f "$WORKSPACE/managed-state.json" ]]; then
    local last_backup
    last_backup=$(jq -r '.last_backup_at // "null"' "$WORKSPACE/managed-state.json" 2>/dev/null || echo "null")
    if [[ "$last_backup" == "null" || -z "$last_backup" ]]; then
      issues+=("no backup found")
      [[ "$status" == "OK" ]] && status="WARN"
    fi
  else
    issues+=("no backup found")
    [[ "$status" == "OK" ]] && status="WARN"
  fi

  record 10 "ops_readiness" "$status" "$(IFS='; '; echo "${issues[*]+"${issues[*]}"}")"
}

# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------
check_workspace_structure
check_permissions
check_bull_json
check_params_json
check_managed_state
check_managed_skills
check_secrets
check_runtime
check_port
check_ops_readiness

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
if [[ "$JSON_OUTPUT" == true ]]; then
  # JSON output
  checks_json="["
  for i in "${!CHECK_NAMES[@]}"; do
    [[ $i -gt 0 ]] && checks_json+=","
    id=$((i + 1))
    # Escape details for JSON
    details="${CHECK_DETAILS[$i]}"
    details="${details//\\/\\\\}"
    details="${details//\"/\\\"}"
    checks_json+="{\"id\":$id,\"name\":\"${CHECK_NAMES[$i]}\",\"status\":\"${CHECK_STATUSES[$i]}\",\"details\":\"$details\"}"
  done
  checks_json+="]"

  cat <<EOJSON
{
  "bull_root": "$BULL_ROOT",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "checks": $checks_json,
  "summary": {"ok": $OK_COUNT, "warn": $WARN_COUNT, "fail": $FAIL_COUNT}
}
EOJSON
else
  # Human-readable output
  echo ""
  echo "  raise-a-bull doctor -- checking $BULL_ROOT/"
  echo ""

  for i in "${!CHECK_NAMES[@]}"; do
    id=$((i + 1))
    # Format check number with padding
    printf " %2d. %-24s" "$id" "${CHECK_NAMES[$i]}"

    status="${CHECK_STATUSES[$i]}"
    details="${CHECK_DETAILS[$i]}"

    case "$status" in
      OK)   printf "[OK]" ;;
      WARN) printf "[WARN]" ;;
      FAIL) printf "[FAIL]" ;;
    esac

    if [[ -n "$details" ]]; then
      printf " %s" "$details"
    fi
    echo ""
  done

  echo ""
  echo "Summary: $OK_COUNT OK, $WARN_COUNT WARN, $FAIL_COUNT FAIL"
fi

# Exit code: 0 if no FAIL, 1 if any FAIL
if [[ $FAIL_COUNT -gt 0 ]]; then
  exit 1
fi
exit 0
