---
name: implement
description: End-to-end implementation of a GitHub Issue — research, implement, test, review, commit, create PR, handle feedback. Use when the user says "implement #N", "work on #N", "start #N", or provides an issue number. This is the workhorse skill for turning an issue into a merged-ready PR.
argument-hint: "#issue-number [--branch name] [--epic #N]"
---

# Implement a GitHub Issue

Execute 5 phases autonomously with tracked progress. The final output is a PR with all CI feedback addressed. Commit, push, and create the PR without asking for permission.

**Progress tracking:** You MUST initialize a TODO checklist at the end of Phase 1 and update it as you complete each step. Before creating the PR (Phase 4), you MUST verify every pre-PR item is done. The TODO list is your memory — if context gets compressed, read it to recover where you are.

Parse `$ARGUMENTS` for: issue number (`#N` or bare number), branch name (`--branch <name>` or derive `work/<N>-<slug>`), epic (`--epic #N` or detect from sub-issues).

## Phase 1: Research

### Read the issue

```bash
gh issue view <NUMBER> -R proteanhq/protean --json title,body,labels,state,milestone
```

If closed, stop and report.

### Read the epic

If the issue is part of an epic (check for "Sub-issue of #N" in the body, or detect via sub-issue relationships), fetch and read the epic:

```bash
gh issue view <EPIC_NUMBER> -R proteanhq/protean --json title,body
```

The epic contains **Design Decisions** and **What Already Exists** sections. These are constraints on your implementation, not suggestions. Treat design decisions (library choices, API shape, config format) as settled unless the issue explicitly says otherwise.

### Read the key files listed in the issue

The issue body has a "Key files" section listing exactly which files to modify. Read those files first — they are your roadmap. Then study recent merged PRs from the same epic to understand established patterns. Read `reference.md` in this skill directory for project conventions.

### Initialize progress checklist

Mark `research` done, then initialize the TODO list with this exact structure:

```
TodoWrite([
  {"id": "research",    "task": "Read issue, epic, and key files",         "status": "pending"},
  {"id": "branch",      "task": "Create branch",                          "status": "pending"},
  {"id": "code",        "task": "Implement changes",                      "status": "pending"},
  {"id": "changelog",   "task": "Create changelog fragment",              "status": "pending"},
  {"id": "self_check",  "task": "Self-check diff",                        "status": "pending"},
  {"id": "simplify",    "task": "Run /simplify — fix issues found",       "status": "pending"},
  {"id": "pr_review",   "task": "Run pr-reviewer agent — fix blockers",   "status": "pending"},
  {"id": "unit_tests",  "task": "Your tests pass",                        "status": "pending"},
  {"id": "core_suite",  "task": "protean test passes",                    "status": "pending"},
  {"id": "quality",     "task": "ruff + mypy pass",                       "status": "pending"},
  {"id": "full_suite",  "task": "make test-full passes (or noted)",       "status": "pending"},
  {"id": "coverage",    "task": "Patch coverage 100%",                    "status": "pending"},
  {"id": "commit_pr",   "task": "Commit, push, create PR",               "status": "pending"},
  {"id": "ci_feedback", "task": "Handle Codecov + Copilot feedback",      "status": "pending"},
])
```

## Phase 2: Implement, simplify, and review

**2a. Branch** — create before writing any code:
```bash
git checkout -b <branch-name> main
# In worktrees where main is checked out elsewhere:
git switch -c <branch-name>
```
→ Mark `branch` done.

**2b. Code** — write minimal, focused changes with type hints. Reuse existing patterns. Handle edge cases.

**2b-ii. Changelog fragment** — create a file in `changes/<issue-number>.<category>.md` (e.g., `changes/752.added.md`). One or two lines, user's perspective. Category is one of: `added`, `changed`, `deprecated`, `removed`, `fixed`, `security`. A single issue may need multiple fragments if it spans categories. Do NOT edit `CHANGELOG.md` directly — fragments are assembled per-epic.

→ Mark `code` and `changelog` done.

**2c. Self-check** — review your diff: docstrings match all code paths, test assertions use non-empty collections, no leftover debug code.

→ Mark `self_check` done.

**2d. Simplify** — run `/simplify` to catch duplicated logic, overcomplexity, and pattern mismatches. You must actually invoke the skill — self-review is not a substitute:
```
Skill(skill="simplify")
```
→ Mark `simplify` done.

**2e. Review** — launch the pr-reviewer agent and fix all blockers it finds. You must actually launch the agent — self-review is not a substitute:
```
Agent(subagent_type="pr-reviewer", prompt="Review the uncommitted changes on this branch. Run `git diff` to see them. Report blockers, suggestions, and good patterns.")
```
→ Mark `pr_review` done.

## Phase 3: Test

Sync the dev environment first (worktrees may have the PyPI package, not local source):
```bash
uv sync --all-extras --all-groups
```

Run in order — each must pass before the next:

1. **Your tests:** `uv run pytest <your-test-file> -v --tb=short` — iterate until green → Mark `unit_tests` done.
2. **Core suite:** `uv run protean test` — fix any failures → Mark `core_suite` done.
3. **Quality checks:** `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/protean` — auto-fix ruff issues, only fix mypy errors you introduced → Mark `quality` done.
4. **Full suite:** `make test-full` (starts Docker + all adapters) — if Docker unavailable, note it and proceed → Mark `full_suite` done.
5. **Patch coverage:** run `uv run diff-cover coverage.xml --compare-branch=main --show-uncovered` if coverage.xml exists, otherwise `uv run pytest <tests> --cov=protean --cov-report=term-missing --cov-config=/dev/null -v` — add tests for any uncovered lines you wrote, target 100% → Mark `coverage` done.

## Preflight gate

**STOP.** Read your TODO list now. Every item from `research` through `coverage` (the first 12 items) must be `done`. If any are still `pending` or `in_progress`, go back and complete them. Do not proceed to Phase 4 until this gate passes.

Items that commonly get skipped — verify you actually did these:
- `simplify` — must have invoked `/simplify`, not just self-reviewed
- `pr_review` — must have launched the pr-reviewer agent, not just self-reviewed
- `full_suite` — must have run `make test-full` or noted Docker unavailable
- `coverage` — must have measured with diff-cover or pytest --cov, not estimated

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

→ Mark `commit_pr` done.

## Phase 5: Handle CI feedback

Poll for Copilot comments and Codecov every 60s, up to 10 minutes. See `reference.md` for the exact `gh api` commands.

**Codecov** is authoritative for coverage. If patch coverage < 100%, add tests, push, wait for re-run. Repeat until 100%.

**Copilot comments** — fix valid issues, reply to each, push as one commit. Re-check mergeability after pushing.

→ Mark `ci_feedback` done.

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
