#!/usr/bin/env bash
set -euo pipefail

# Scan skills for hardcoded secrets or credentials
# Usage: ./scripts/sanitize.sh [skills-path] [--strict]
# Default: scans repo's skills/ directory
# With path: scans specified directory (e.g., ~/bulls/X/workspace/skills/)
# Exit code: 0 = clean, 1 = found issues

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATTERNS_FILE="$SCRIPT_DIR/.sanitize-patterns"
IGNORE_FILE="$SCRIPT_DIR/.sanitize-ignore"

# Parse arguments
STRICT=false
TARGET_PATH=""

for arg in "$@"; do
  case "$arg" in
    --strict) STRICT=true ;;
    *) TARGET_PATH="$arg" ;;
  esac
done

# Default target: skills/ directory relative to repo root
if [[ -z "$TARGET_PATH" ]]; then
  TARGET_PATH="$SCRIPT_DIR/../skills"
fi

# Resolve to absolute path
TARGET_PATH="$(cd "$TARGET_PATH" 2>/dev/null && pwd)" || {
  echo "ERROR: Target path does not exist: $TARGET_PATH"
  exit 1
}

# Verify patterns file exists
if [[ ! -f "$PATTERNS_FILE" ]]; then
  echo "ERROR: Patterns file not found: $PATTERNS_FILE"
  exit 1
fi

# Load ignore patterns (if file exists)
IGNORE_PATTERNS=()
if [[ -f "$IGNORE_FILE" ]]; then
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    IGNORE_PATTERNS+=("$line")
  done < "$IGNORE_FILE"
fi

# Find all .md files
MD_FILES=()
while IFS= read -r f; do
  MD_FILES+=("$f")
done < <(find "$TARGET_PATH" -type f -name "*.md" | sort)

if [[ ${#MD_FILES[@]} -eq 0 ]]; then
  echo "No .md files found in $TARGET_PATH"
  echo "Summary: 0 files scanned, 0 issues found"
  exit 0
fi

# Load patterns
PATTERNS=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  PATTERNS+=("$line")
done < "$PATTERNS_FILE"

# Scan files
ISSUES=0
FILES_SCANNED=0

for file in "${MD_FILES[@]}"; do
  FILES_SCANNED=$((FILES_SCANNED + 1))
  rel_path="${file#"$TARGET_PATH"/}"

  for pattern in "${PATTERNS[@]}"; do
    # Use grep -nE; suppress errors for binary/unreadable files
    while IFS= read -r match_line; do
      line_num="${match_line%%:*}"
      line_content="${match_line#*:}"

      # Check against ignore patterns
      skip=false
      for ignore in "${IGNORE_PATTERNS[@]+"${IGNORE_PATTERNS[@]}"}"; do
        if echo "$line_content" | grep -qE "$ignore" 2>/dev/null; then
          skip=true
          break
        fi
      done

      if [[ "$skip" == false ]]; then
        echo "$rel_path:$line_num: matched pattern: $pattern"
        ISSUES=$((ISSUES + 1))
      fi
    done < <(grep -nE "$pattern" "$file" 2>/dev/null || true)
  done
done

echo ""
echo "Summary: $FILES_SCANNED files scanned, $ISSUES issues found"

if [[ $ISSUES -gt 0 ]]; then
  if [[ "$STRICT" == true ]]; then
    echo "STRICT MODE: Failing due to $ISSUES issue(s)"
    exit 1
  else
    echo "WARNING: Found potential secrets. Review matches above."
    exit 1
  fi
fi

exit 0
