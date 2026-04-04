---
name: implement
description: End-to-end implementation of a GitHub Issue — research, implement, test, review, commit, create PR, handle feedback. Use when the user says "implement #N", "work on #N", "start #N", or provides an issue number. This is the workhorse skill for turning an issue into a merged-ready PR.
argument-hint: "#issue-number [--branch name] [--epic #N]"
---

# Implement a GitHub Issue

Run all 5 phases to completion. The user expects a PR as the output — not a summary, not a plan, not a question. Commit, push, and create the PR without asking. The only reasons to pause: an unresolvable failure, or a genuine ambiguity between two incompatible implementations.

## Parse arguments

Extract from `$ARGUMENTS`:
- **Issue number** (required) — `#N` or bare number. Multiple `#N` references: smaller = issue, larger = epic.
- **Branch name** — `--branch <name>`, or derive as `work/<issue-number>-<slug>` from the issue title
- **Epic number** — `--epic #N`, or detect from sub-issue relationships, or "Epic #N" in input

## Phase 1: Research

```bash
gh issue view <NUMBER> -R proteanhq/protean --json title,body,labels,state,milestone
```

If the issue is closed, stop and report. Otherwise, read the epic too if one exists.

Study recent merged PRs from the same epic (`gh pr list -R proteanhq/protean --state merged --limit 10`) and read diffs of related ones. Then deep-dive the source files you'll modify — understand patterns, existing utilities, test structure. Read `reference.md` in this skill directory for project-specific conventions.

## Phase 2: Implement

Log one line: "Research complete. Implementing: [1-sentence summary]." — then write code.

Create the branch (`git checkout -b <branch-name> main` or `git switch -c <branch-name>` in worktrees). Write minimal, focused changes with type hints. Reuse existing patterns. Handle edge cases.

Do a quick self-check of your diff: docstrings match all code paths, test loops assert non-empty collections first, no leftover debug code. Then immediately run simplify and review (Phases 3-4) before testing:

```
Skill(skill="simplify")
```

Then launch the pr-reviewer agent:

```
Agent(subagent_type="pr-reviewer", prompt="Review the uncommitted changes on this branch. Run `git diff` to see them. Report blockers, suggestions, and good patterns.")
```

Fix all blockers from the review. Take suggestions that improve clarity or correctness.

## Phase 3: Test

Run these in order. Each must pass before the next.

**Step 1 — Your tests:** `uv run pytest <your-test-file> -v --tb=short`. Iterate until green.

**Step 2 — Core suite:** `uv run protean test`. Fix any failures.

**Step 3 — Quality checks:** `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/ && uv run mypy src/protean`. Auto-fix ruff issues. Only fix mypy errors you introduced.

**Step 4 — Full suite:** `make test-full` (starts Docker + runs all adapters). If Docker is unavailable, note it and proceed — CI runs the full matrix.

**Step 5 — Patch coverage:** If `coverage.xml` exists from Step 4, run `uv run diff-cover coverage.xml --compare-branch=main --show-uncovered`. For any uncovered lines you wrote, add tests and re-check. Target 100%. If no `coverage.xml`, use `uv run pytest <tests> --cov=protean --cov-report=term-missing --cov-config=/dev/null -v`.

## Phase 4: Commit and PR

**Rebase first:** `git fetch origin main && git rebase origin/main`. Re-run your tests if conflicts arose.

**Changelog:** Add an entry under `[Unreleased]` in CHANGELOG.md. Write from the user's perspective.

**Breaking changes:** If you renamed, removed, or changed behavior of anything in `protean.*`, apply the appropriate deprecation tier (see CLAUDE.md).

**Commit:** `git add <specific-files>` then commit. Message starts with a verb, no AI attribution, no Co-Authored-By.

**PR:** Push and create with `gh pr create -R proteanhq/protean`. Title under 70 chars. Body includes Summary, Test plan, and `Closes #<ISSUE>`.

**Mergeability:** `gh pr view <PR> -R proteanhq/protean --json mergeable,mergeStateStatus,statusCheckRollup`. Rebase + force-push if conflicts exist.

## Phase 5: Handle CI feedback

Poll for Copilot comments and CI status every 60s, up to 10 minutes:

```bash
gh api repos/proteanhq/protean/pulls/<PR>/comments --jq 'length'
gh pr checks <PR> -R proteanhq/protean
```

**Codecov:** Fetch the Codecov bot comment (`gh api repos/proteanhq/protean/issues/<PR>/comments --jq '.[] | select(.user.login == "codecov[bot]" or .user.login == "codecov-commenter") | .body'`). Codecov is authoritative — if patch coverage < 100%, add tests, push, and wait for re-run. Repeat until 100%.

**Copilot comments:** Fetch with `gh api repos/proteanhq/protean/pulls/<PR>/comments --jq '.[] | {id, path, body, line, in_reply_to_id}'`. Fix valid issues, reply to each (`gh api repos/proteanhq/protean/pulls/<PR>/comments/<ID>/replies -f body='Fixed — ...'`), push as one commit.

**Re-check mergeability** after pushing fixes.

## Report

```
Issue: #N — Title
Branch: work/branch-name
PR: #M — PR Title (URL)

Changes:
- (1-3 bullets)

Tests:
- X tests added, all passing
- Core suite: Y passed, 0 failed
- Full suite: Z passed, 0 failed
- Patch coverage: N% (Codecov)

Review:
- N comments addressed
- PR is mergeable, CI passing
```

Never merge the PR.
