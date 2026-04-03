#!/bin/bash
# PreToolUse hook: Prevent Claude from modifying linter/formatter/CI configs.
# If a lint or format check fails, Claude should fix the code, not weaken the rules.

TOOL_NAME_VAR="${TOOL_NAME:-}"

# For Edit/Write tools, check the file path
if [ "$TOOL_NAME_VAR" = "Edit" ] || [ "$TOOL_NAME_VAR" = "Write" ]; then
    FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.file_path // ""' 2>/dev/null)
else
    # For Bash, check if command modifies protected files
    COMMAND=$(echo "$TOOL_INPUT" | jq -r '.command // ""' 2>/dev/null)

    # Check if bash command writes to protected files
    PROTECTED_PATTERNS=(
        "pyproject.toml.*\[tool\.ruff"
        "pyproject.toml.*\[tool\.mypy"
        "\.pre-commit-config"
        "\.github/workflows"
    )

    for pattern in "${PROTECTED_PATTERNS[@]}"; do
        if echo "$COMMAND" | grep -qE "(sed|awk|echo|cat|tee).*${pattern}"; then
            echo "BLOCKED: Modifying linter/CI config via shell command. Fix the code instead of weakening the rules." >&2
            exit 2
        fi
    done
    exit 0
fi

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

BASENAME=$(basename "$FILE_PATH")

# Protected config files
case "$BASENAME" in
    .pre-commit-config.yaml)
        echo "BLOCKED: .pre-commit-config.yaml is protected. Fix the code to pass pre-commit checks instead." >&2
        exit 2
        ;;
esac

# Check for ruff/mypy sections in pyproject.toml
if [ "$BASENAME" = "pyproject.toml" ]; then
    # Read the old_string or content to see if it touches lint config
    OLD_STRING=$(echo "$TOOL_INPUT" | jq -r '.old_string // ""' 2>/dev/null)
    NEW_STRING=$(echo "$TOOL_INPUT" | jq -r '.new_string // ""' 2>/dev/null)
    CONTENT=$(echo "$TOOL_INPUT" | jq -r '.content // ""' 2>/dev/null)

    CHECK_TEXT="${OLD_STRING}${NEW_STRING}${CONTENT}"

    if echo "$CHECK_TEXT" | grep -qE '\[tool\.(ruff|mypy|pytest)'; then
        echo "BLOCKED: Modifying [tool.ruff], [tool.mypy], or [tool.pytest] in pyproject.toml is not allowed. Fix the code to comply with existing rules." >&2
        exit 2
    fi
fi

exit 0
