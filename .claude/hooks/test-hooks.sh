#!/bin/bash
# Smoke tests for the PreToolUse safety hooks.
#
# Verifies block-dangerous-git.sh and protect-config.sh BLOCK (exit 2) dangerous
# operations and ALLOW (exit 0) safe ones — under BOTH input mechanisms: the
# legacy $TOOL_INPUT/$TOOL_NAME env vars and the stdin JSON payload that current
# Claude Code delivers.
#
# Run:  bash .claude/hooks/test-hooks.sh
# Exits non-zero if any case fails (suitable for CI).

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
BLOCK="$HOOK_DIR/block-dangerous-git.sh"
PROTECT="$HOOK_DIR/protect-config.sh"

pass=0
fail=0

expect() {
    local expected=$1 actual=$2 desc=$3
    if [ "$actual" -eq "$expected" ]; then
        echo "  PASS  $desc"
        pass=$((pass + 1))
    else
        echo "  FAIL  $desc (expected exit $expected, got $actual)"
        fail=$((fail + 1))
    fi
}

echo "block-dangerous-git.sh — env var input:"
TOOL_INPUT='{"command":"git push --force"}' bash "$BLOCK" </dev/null; expect 2 $? "force push blocked"
TOOL_INPUT='{"command":"git commit --no-verify -m x"}' bash "$BLOCK" </dev/null; expect 2 $? "--no-verify blocked"
TOOL_INPUT='{"command":"git reset --hard HEAD~1"}' bash "$BLOCK" </dev/null; expect 2 $? "reset --hard blocked"
TOOL_INPUT='{"command":"git clean -fd"}' bash "$BLOCK" </dev/null; expect 2 $? "git clean -f blocked"
TOOL_INPUT='{"command":"git checkout ."}' bash "$BLOCK" </dev/null; expect 2 $? "checkout . blocked"
TOOL_INPUT='{"command":"git status"}' bash "$BLOCK" </dev/null; expect 0 $? "git status allowed"
TOOL_INPUT='{"command":"git push --force-with-lease"}' bash "$BLOCK" </dev/null; expect 0 $? "force-with-lease allowed"

echo "block-dangerous-git.sh — stdin payload input:"
printf '%s' '{"tool_input":{"command":"git push --force"}}' | env -u TOOL_INPUT bash "$BLOCK"; expect 2 $? "force push blocked (stdin)"
printf '%s' '{"tool_input":{"command":"git status"}}' | env -u TOOL_INPUT bash "$BLOCK"; expect 0 $? "git status allowed (stdin)"

echo "protect-config.sh — env var input:"
TOOL_NAME=Edit TOOL_INPUT='{"file_path":".pre-commit-config.yaml"}' bash "$PROTECT" </dev/null; expect 2 $? "edit .pre-commit-config blocked"
TOOL_NAME=Edit TOOL_INPUT='{"file_path":"pyproject.toml","new_string":"[tool.ruff]\nline-length=200"}' bash "$PROTECT" </dev/null; expect 2 $? "edit [tool.ruff] in pyproject blocked"
TOOL_NAME=Edit TOOL_INPUT='{"file_path":"src/protean/core/aggregate.py"}' bash "$PROTECT" </dev/null; expect 0 $? "edit source file allowed"
TOOL_NAME=Bash TOOL_INPUT='{"command":"sed -i s/x/y/ .pre-commit-config.yaml"}' bash "$PROTECT" </dev/null; expect 2 $? "bash modifying config blocked"
TOOL_NAME=Bash TOOL_INPUT='{"command":"ls -la"}' bash "$PROTECT" </dev/null; expect 0 $? "bash ls allowed"

echo "protect-config.sh — stdin payload input:"
printf '%s' '{"tool_name":"Edit","tool_input":{"file_path":".pre-commit-config.yaml"}}' | env -u TOOL_INPUT -u TOOL_NAME bash "$PROTECT"; expect 2 $? "edit .pre-commit-config blocked (stdin)"
printf '%s' '{"tool_name":"Edit","tool_input":{"file_path":"src/protean/core/aggregate.py"}}' | env -u TOOL_INPUT -u TOOL_NAME bash "$PROTECT"; expect 0 $? "edit source file allowed (stdin)"

echo ""
echo "Results: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
