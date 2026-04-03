#!/bin/bash
# PreCompact hook: Save working context before context compression.
# Writes current tasks, modified files, and active branch info to a scratch file
# so the conversation can recover state after compaction.

set -e
cd "$CLAUDE_PROJECT_DIR"

SCRATCH_DIR=".claude/scratch"
mkdir -p "$SCRATCH_DIR"
SCRATCH_FILE="$SCRATCH_DIR/pre-compact-state.md"

{
    echo "# Pre-Compact State"
    echo "Saved: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo ""

    echo "## Branch"
    git branch --show-current 2>/dev/null || echo "(detached)"
    echo ""

    echo "## Modified files"
    git diff --name-only HEAD 2>/dev/null || echo "(none)"
    echo ""

    echo "## Staged files"
    git diff --cached --name-only 2>/dev/null || echo "(none)"
    echo ""

    echo "## Recent commits (this branch vs main)"
    git log main..HEAD --oneline 2>/dev/null | head -10 || echo "(none)"
    echo ""

    echo "## Active plan files"
    ls -t .claude/plans/*.md 2>/dev/null | head -3 || echo "(none)"

} > "$SCRATCH_FILE"

exit 0
