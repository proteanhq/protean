#!/bin/bash
# Stop hook: Remind about CHANGELOG.md if src/ files were modified but CHANGELOG wasn't.
# Outputs a reminder to stderr (shown as hook feedback) — doesn't block anything.

set -e
cd "$CLAUDE_PROJECT_DIR"

# Check if any src/ files are modified (staged or unstaged)
SRC_CHANGED=$(git diff --name-only HEAD -- 'src/' 2>/dev/null || true)
if [ -z "$SRC_CHANGED" ]; then
    SRC_CHANGED=$(git diff --name-only -- 'src/' 2>/dev/null || true)
fi

if [ -z "$SRC_CHANGED" ]; then
    exit 0
fi

# Check if CHANGELOG.md is also modified
CHANGELOG_CHANGED=$(git diff --name-only HEAD -- 'CHANGELOG.md' 2>/dev/null || true)
if [ -z "$CHANGELOG_CHANGED" ]; then
    CHANGELOG_CHANGED=$(git diff --name-only -- 'CHANGELOG.md' 2>/dev/null || true)
fi

if [ -z "$CHANGELOG_CHANGED" ]; then
    echo '{"result": "CHANGELOG reminder: src/ files have been modified but CHANGELOG.md has not. Remember to add an entry under [Unreleased] before creating a PR."}'
fi

exit 0
