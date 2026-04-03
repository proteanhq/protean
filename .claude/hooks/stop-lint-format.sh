#!/bin/bash
# Stop hook: Auto-format and lint src/ after every Claude response.
# Runs ruff check --fix (auto-fixable lint issues) then ruff format.
# Only operates on files that git sees as modified to avoid full-tree scans.

set -e
cd "$CLAUDE_PROJECT_DIR"

# Get modified Python files in src/ (staged + unstaged)
CHANGED=$(git diff --name-only --diff-filter=ACMR HEAD -- 'src/*.py' 'src/**/*.py' 2>/dev/null || true)
UNSTAGED=$(git diff --name-only --diff-filter=ACMR -- 'src/*.py' 'src/**/*.py' 2>/dev/null || true)
UNTRACKED=$(git ls-files --others --exclude-standard -- 'src/*.py' 'src/**/*.py' 2>/dev/null || true)

FILES=$(echo -e "${CHANGED}\n${UNSTAGED}\n${UNTRACKED}" | sort -u | grep -v '^$' || true)

if [ -z "$FILES" ]; then
    exit 0
fi

# Run ruff check with auto-fix on changed files only
echo "$FILES" | xargs uv run ruff check --fix --quiet 2>&1 | tail -20 || true

# Run ruff format on changed files only
echo "$FILES" | xargs uv run ruff format --quiet 2>&1 | tail -10 || true

exit 0
