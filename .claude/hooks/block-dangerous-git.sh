#!/bin/bash
# PreToolUse hook: Block dangerous git operations.
# Exit code 2 = block the tool use.

COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // ""' 2>/dev/null)

if [ -z "$COMMAND" ]; then
    exit 0
fi

# Block --no-verify (skips pre-commit hooks)
if echo "$COMMAND" | grep -qE '\-\-no-verify'; then
    echo "BLOCKED: --no-verify is not allowed. Fix the pre-commit hook issue instead." >&2
    exit 2
fi

# Block force push
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force|git\s+push\s+-f\b'; then
    echo "BLOCKED: Force push is not allowed. Use --force-with-lease if absolutely necessary." >&2
    exit 2
fi

# Block git reset --hard
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard'; then
    echo "BLOCKED: git reset --hard can destroy uncommitted work. Use git stash or git checkout <file> instead." >&2
    exit 2
fi

# Block git clean -f (deletes untracked files)
if echo "$COMMAND" | grep -qE 'git\s+clean\s+-[a-zA-Z]*f'; then
    echo "BLOCKED: git clean -f deletes untracked files permanently. Be explicit about what to remove." >&2
    exit 2
fi

# Block git checkout . (discards all changes)
if echo "$COMMAND" | grep -qE 'git\s+checkout\s+\.\s*$'; then
    echo "BLOCKED: git checkout . discards all uncommitted changes. Use git stash or be specific about files." >&2
    exit 2
fi

# Block git restore . (discards all changes)
if echo "$COMMAND" | grep -qE 'git\s+restore\s+\.\s*$'; then
    echo "BLOCKED: git restore . discards all uncommitted changes. Be specific about files." >&2
    exit 2
fi

exit 0
