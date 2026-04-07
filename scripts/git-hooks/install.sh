#!/bin/bash
# Install repo git hooks into .git/hooks/.
# Run once after cloning, or after pulling hook updates.
#
# Currently only pre-push is tracked. Add new hook names to the HOOKS variable
# below if more get tracked later.

set -e

cd "$(git rev-parse --show-toplevel)"

if [ ! -d .git/hooks ]; then
    echo "❌ .git/hooks directory not found — are you in a git working tree?"
    exit 1
fi

HOOKS="pre-push"
for hook in $HOOKS; do
    src="scripts/git-hooks/$hook"
    if [ ! -f "$src" ]; then
        echo "❌ $src not found — repo missing tracked hook source"
        exit 1
    fi
    target=".git/hooks/$hook"
    cp "$src" "$target"
    chmod +x "$target"
    echo "✅ Installed $hook → $target"
done
