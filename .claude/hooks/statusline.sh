#!/bin/bash
# Status line: "<model> · <dir> ⎇ <branch>[*] · <N> frag(s)"
# Reads the session JSON on stdin; prints one line. Always exits 0 (fail-open).
# Local-only: a git branch/dirty check and a count of changelog fragments.

INPUT=$(cat 2>/dev/null || true)

model=$(printf '%s' "$INPUT" | jq -r '.model.display_name // "Claude"' 2>/dev/null)
dir=$(printf '%s' "$INPUT" | jq -r '.workspace.current_dir // .cwd // ""' 2>/dev/null)
[ -z "$dir" ] && dir="${CLAUDE_PROJECT_DIR:-$PWD}"

name=$(basename "$dir" 2>/dev/null)

branch=""
if git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    branch=$(git -C "$dir" branch --show-current 2>/dev/null)
    [ -z "$branch" ] && branch="(detached)"
    [ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ] && branch="${branch}*"
fi

frags=0
if [ -d "$dir/changes" ]; then
    frags=$(find "$dir/changes" -maxdepth 1 -name '*.md' ! -name 'README.md' 2>/dev/null | wc -l | tr -d ' ')
fi

line="$model"
[ -n "$name" ] && line="$line · $name"
[ -n "$branch" ] && line="$line ⎇ $branch"
[ "${frags:-0}" -gt 0 ] 2>/dev/null && line="$line · ${frags} frag(s)"

printf '%s\n' "$line"
exit 0
