---
name: implement
description: End-to-end implementation of a GitHub Issue — research, implement, test, review, commit, create PR, handle feedback. Use when the user says "implement #N", "work on #N", "start #N", or provides an issue number. This is the workhorse skill for turning an issue into a merged-ready PR.
argument-hint: "#issue-number [--branch name] [--epic #N]"
---

# Implement a GitHub Issue

Execute 5 phases autonomously. The final output is a PR with all CI feedback addressed. Commit, push, and create the PR without asking for permission.

Parse `$ARGUMENTS` for: issue number (`#N` or bare number), branch name (`--branch <name>` or derive `work/<N>-<slug>`), epic (`--epic #N` or detect from sub-issues).

## Phase 1: Research

Fetch the issue and understand what's needed:

```bash
gh issue view <NUMBER> -R proteanhq/protean --json title,body,labels,state,milestone
```

If closed, stop and report. If part of an epic, read the epic too. Study recent merged PRs from the same epic — read diffs of related ones to understand established patterns. Deep-dive the source files you'll modify. Read `reference.md` in this skill directory for project conventions.

## Phase 2: Implement, simplify, and review

**2a. Branch** — create before writing any code:
```bash
git checkout -b <branch-name> main
# In worktrees where main is checked out elsewhere:
git switch -c <branch-name>
```

**2b. Code** — write minimal, focused changes with type hints. Reuse existing patterns. Handle edge cases.

**2b-ii. Changelog fragment** — create a file in `changes/<issue-number>.<category>.md` (e.g., `changes/752.added.md`). One or two lines, user's perspective. Category is one of: `added`, `changed`, `deprecated`, `removed`, `fixed`, `security`. A single issue may need multiple fragments if it spans categories. Do NOT edit `CHANGELOG.md` directly — fragments are assembled per-epic.

**2c. Self-check** — review your diff: docstrings match all code paths, test assertions use non-empty collections, no leftover debug code.

**2d. Simplify** — run `/simplify` to catch duplicated logic, overcomplexity, and pattern mismatches:
```
Skill(skill="simplify")
```

**2e. Review** — launch the pr-reviewer agent and fix all blockers it finds:
```
Agent(subagent_type="pr-reviewer", prompt="Review the uncommitted changes on this branch. Run `git diff` to see them. Report blockers, suggestions, and good patterns.")
```

## Phase 3: Test

Sync the dev environment first (worktrees may have the PyPI package, not local source):
```bash
uv sync --all-extras --all-groups
```

Run in order — each must pass before the next:

1. **Your tests:** `uv run pytest <your-test-file> -v --tb=short` — iterate until green
2. **Core suite:** `uv run protean test` — fix any failures
3. **Quality checks:** `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/protean` — auto-fix ruff issues, only fix mypy errors you introduced
4. **Full suite:** `make test-full` (starts Docker + all adapters) — if Docker unavailable, note it and proceed
5. **Patch coverage:** run `uv run diff-cover coverage.xml --compare-branch=main --show-uncovered` if coverage.xml exists, otherwise `uv run pytest <tests> --cov=protean --cov-report=term-missing --cov-config=/dev/null -v` — add tests for any uncovered lines you wrote, target 100%

## Phase 4: Commit and PR

Rebase first: `git fetch origin main && git rebase origin/main`. Re-run tests if conflicts arose. Check for breaking changes (see CLAUDE.md for deprecation tiers).

Commit with `git add <specific-files>` — message starts with a verb, no AI attribution, no Co-Authored-By. Push and create PR:
```bash
git push -u origin HEAD
gh pr create -R proteanhq/protean --title "<title>" --body "$(cat <<'EOF'
## Summary
- Key changes

## Test plan
- [ ] Core tests pass
- [ ] Full adapter suite passes
- [ ] 100% patch coverage

Closes #<ISSUE>
EOF
)"
```

Check mergeability: `gh pr view <PR> -R proteanhq/protean --json mergeable,mergeStateStatus,statusCheckRollup`. Rebase + force-push if conflicts.

## Phase 5: Handle CI feedback

Poll for Copilot comments and Codecov every 60s, up to 10 minutes. See `reference.md` for the exact `gh api` commands.

**Codecov** is authoritative for coverage. If patch coverage < 100%, add tests, push, wait for re-run. Repeat until 100%.

**Copilot comments** — fix valid issues, reply to each, push as one commit. Re-check mergeability after pushing.

## Report

When complete, output this summary:
```
Issue: #N — Title
Branch: work/branch-name
PR: #M — PR Title (URL)
Changes: (1-3 bullets)
Tests: X added, core Y/0, full Z/0, patch coverage N%
Review: N comments addressed, PR mergeable, CI passing
```

Never merge the PR.
