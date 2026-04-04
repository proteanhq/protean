---
name: implement
description: End-to-end implementation of a GitHub Issue — research the issue and epic context, deep-dive the codebase, implement changes, self-review, test with coverage, commit, create a PR, and handle review feedback. Use this skill when the user says "implement #N", "work on #N", "start #N", "pick up this issue", "build this feature", or provides an issue number with optional branch/epic context. Also trigger when the user pastes a task block with issue details, says "take this from start to finish", or gives a bare issue number expecting autonomous implementation. This is the workhorse skill for turning an issue into a merged-ready PR.
argument-hint: "#issue-number [--branch name] [--epic #N]"
---

# Implement a GitHub Issue

Take a GitHub Issue through the full lifecycle: understand it, implement it, test it, ship a PR, and handle review feedback. The goal is a PR that's ready for human review — well-tested, well-described, and following every project convention.

## Parse arguments

Extract from `$ARGUMENTS`:
- **Issue number** (required) — `#N` or bare number
- **Branch name** — `--branch <name>`, or derive as `work/<issue-number>-<slug>` from the issue title
- **Epic number** — `--epic #N` for parent context, or detect from the issue's sub-issue relationships

## Phase 1: Research

Don't write code yet. The quality of your implementation depends on how well you understand the problem and the codebase around it.

### Read the issue

```bash
gh issue view <NUMBER> -R proteanhq/protean --json title,body,labels,state,milestone
```

**Gate: check issue state.** If the issue is already closed, stop and report: "Issue #N is already closed (merged via PR #X on DATE). Did you mean a different issue?" Don't proceed with implementation of a closed issue unless the user explicitly asks to re-implement or extend it.

If an epic was provided or the issue is a sub-issue of one, read the epic too — it has the broader context for why this work matters:

```bash
gh issue view <EPIC_NUMBER> -R proteanhq/protean --json title,body,labels
```

Understand the acceptance criteria, not just the title.

### Study recent work on the epic

If this issue is part of an epic with prior completed sub-issues, the recent PRs contain critical context — patterns established, APIs introduced, conventions set by earlier work in the same epic:

```bash
gh pr list -R proteanhq/protean --state merged --limit 10 --json number,title,headRefName
```

For related PRs (same epic, similar branch prefix), read their diffs:

```bash
gh pr diff <NUMBER> -R proteanhq/protean
```

This prevents you from duplicating work, contradicting decisions already made, or missing utilities that were introduced two PRs ago.

### Deep-dive the codebase

Read the actual source files you'll modify. Understand:

- Existing patterns and conventions in the module you're touching
- Utilities, helpers, or base classes that already exist — reuse, don't reinvent
- How tests are structured for similar features (test placement: `src/protean/core/foo.py` → `tests/foo/`)
- The `test_domain` fixture — it creates a domain named "Test", so stream prefixes are "test::"

Don't skip this. A shallow read leads to code that works but doesn't fit.

## Phase 2: Implement

Before starting Phase 2, confirm: "Research complete. The issue requires [1-sentence summary]. Proceeding with implementation."

### Create the branch

```bash
git checkout -b <branch-name> main
```

If `git checkout` is blocked (e.g., in a worktree where `main` is checked out elsewhere), use:

```bash
git switch -c <branch-name>
```

### Write the code

Follow these principles — they come from hard-won experience on this project:

- **Minimal, focused changes** — only what the issue requires
- **Reuse existing patterns** — match how adjacent code does similar things
- **Type hints on all new code** — and existing code you touch
- **Handle edge cases** — especially in middleware, integrations, and event processing. Cover the "no header", "no domain context", "no command processed" paths, not just the happy path
- **Intentional exports** — when adding to `__init__.py`, make sure the public API surface change is deliberate

### Self-review before committing

Before you commit, review your own work as if you were a hostile reviewer. These are the actual bugs that slip through most often:

1. **Docstrings must match behavior.** If a docstring says "always includes X", verify the code actually does that for ALL code paths. Middleware that claims to set a response header must set it even when no command was processed, no domain context exists, etc.

2. **Tests must exercise their assertions.** The single most common silent failure: a loop that iterates over an empty collection, so all assertions inside it pass vacuously. Always assert the collection is non-empty first:
   ```python
   assert len(events) > 0, "Expected events but got none"
   for event in events:
       assert event.correlation_id is not None
   ```

3. **Event store stream names include the domain prefix.** The format is `{domain_name}::{stream}`. Fact events use `-fact-` in the stream name. With `test_domain`, streams look like `test::user-fact-v1`.

4. **Fact events require opt-in.** If testing event propagation, the aggregate must have `fact_events=True` — otherwise no events are produced and your test silently asserts nothing.

5. **No leftover debug code.** No stray `print()`, `breakpoint()`, or commented-out blocks.

## Phase 3: Test

All testing must pass **before** committing. Follow these steps in order.

### Step 1: Fast iteration on your tests

```bash
uv run pytest <your-test-file> -v --tb=short
```

Iterate until your new tests pass. Fix bugs in both production code and tests.

### Step 2: Core tests (no adapters)

Run the full core test suite with in-memory adapters — no external services needed:

```bash
uv run protean test
```

**Gate: every core test must pass.** If any test fails, investigate and fix before proceeding. Do not skip or ignore failures — they indicate either a regression in your code or a pre-existing issue that must be understood.

### Step 3: Full suite with adapters

Start all external services (Redis, PostgreSQL, Elasticsearch, MessageDB):

```bash
make up
```

Wait for services to be ready, then run the full test suite with all adapter configurations:

```bash
uv run protean test -c FULL
```

**Gate: all tests must pass.** Adapter test failures may indicate that your changes broke compatibility with real infrastructure. Fix before proceeding.

### Step 4: Coverage of new code

Measure coverage specifically on the files you changed:

```bash
uv run pytest <your-test-files> --cov=protean --cov-report=term-missing --cov-config=/dev/null -v
```

Use `--cov=protean` (module name, not path) and `--cov-config=/dev/null` to bypass any .coveragerc that might exclude test files.

**Gate: aim for 100% coverage on lines you wrote.** If a line in your new or modified code isn't covered, write a test for it. Every branch, every error path, every edge case. Uncovered lines are untested behavior.

### Testing conventions

- **No mocks.** Register real domain elements: `test_domain.register(MyAggregate)` then `test_domain.init(traverse=False)`.
- **Tests ship with code.** Same commit, same PR. Never a separate "add tests" step.
- **Test placement follows source layout.** `src/protean/core/aggregate.py` → `tests/aggregate/`.

## Phase 4: Commit and PR

**Prerequisite: Phase 3 must be fully complete** — core tests pass, full adapter suite passes, and coverage meets the 100% target on new code. Do not commit untested or partially tested code.

### Commit

Stage only the files you changed:

```bash
git add <specific-files>
git commit -m "$(cat <<'EOF'
Concise description of what and why

EOF
)"
```

Commit message rules:
- Start with a verb: Add, Fix, Update, Remove, Refactor
- No Claude attribution, no session links, no AI mention
- No "Co-Authored-By" lines
- Don't override git user config — it's already set correctly

### Changelog entry

Read `CHANGELOG.md` and add an entry under `[Unreleased]` in the appropriate subsection (Added, Changed, Fixed, etc.). Write from the user's perspective — what changed for them, not what files were edited.

### Check for breaking changes

If your diff renames, removes, or changes behavior of anything in `protean.*` that user code could depend on:

- **Tier 1 (surface — renamed/moved)**: Add a deprecation wrapper that delegates to the new implementation
- **Tier 2 (behavioral — same API, different behavior)**: Flag to user — needs a config flag
- **Tier 3 (structural — persistence format, event schema)**: Flag to user — needs migration docs

Don't proceed silently with unmitigated breaks.

### Push and create the PR

```bash
git push -u origin HEAD
gh pr create -R proteanhq/protean --title "PR title" --body "$(cat <<'EOF'
## Summary
- Key change 1
- Key change 2

## Test plan
- [ ] Core tests pass (`protean test`)
- [ ] Full adapter suite passes (`protean test -c FULL`)
- [ ] 100% coverage on new/modified code

Closes #<ISSUE_NUMBER>

EOF
)"
```

Title: under 70 characters, starts with a verb.

## Phase 5: Handle review feedback

After creating the PR, poll for Copilot review comments (they typically arrive within 2-5 minutes):

```bash
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments --jq 'length'
```

Check every 60 seconds, up to 10 minutes. Once comments arrive:

```bash
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments --jq '.[] | {id, path, body, line, in_reply_to_id}'
```

### Triage each comment

For each top-level comment (`in_reply_to_id` is null):

- **Agree and fix** — the comment identifies a real issue. Fix the code.
- **Disagree** — the comment misunderstands a project convention. Prepare a reasoned reply.
- **Out of scope** — acknowledge and explain.

### Common Copilot catches to preempt

These are the patterns Copilot flags most often on this project — catching them in self-review (Phase 2) saves a round trip:

- Tests that loop over collections without asserting the collection is non-empty
- Docstrings that promise behavior the code doesn't deliver for all paths
- Missing auto-generation of IDs when "always present" semantics are documented
- Assertions that test implementation details rather than behavior

### Fix, push, reply, resolve

Batch fixes into one commit:

```bash
git add <fixed-files>
git commit -m "Address review feedback on PR #<NUMBER>"
git push
```

Reply to each comment:

```bash
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments \
  -f body="Fixed — one sentence explaining the change." \
  -F in_reply_to=<COMMENT_ID>
```

Resolve all threads:

```bash
gh api graphql -f query='{ repository(owner: "proteanhq", name: "protean") {
  pullRequest(number: <PR_NUMBER>) {
    reviewThreads(first: 50) {
      nodes { id isResolved comments(first: 1) { nodes { databaseId } } }
    }
  }
} }'

gh api graphql -f query='mutation { resolveReviewThread(input: { threadId: "<THREAD_ID>" }) { thread { isResolved } } }'
```

## Report

When complete, summarize:

```
Issue: #N — Title
Branch: work/branch-name
PR: #M — PR Title (URL)

Changes:
- What was implemented (1-3 bullets)

Tests:
- X tests added, all passing
- Core suite (`protean test`): Y passed, 0 failed
- Full suite (`protean test -c FULL`): Z passed, 0 failed
- Coverage on new code: N%

Review:
- N comments addressed, all threads resolved
```

Never merge the PR — leave that to the user.
