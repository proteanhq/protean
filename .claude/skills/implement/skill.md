---
name: implement
description: End-to-end implementation of a GitHub Issue — research the issue and epic context, deep-dive the codebase, implement changes, self-review, test with coverage, commit, create a PR, and handle review feedback. Use this skill when the user says "implement #N", "work on #N", "start #N", "pick up this issue", "build this feature", or provides an issue number with optional branch/epic context. Also trigger when the user pastes a task block with issue details, says "take this from start to finish", gives a bare issue number expecting autonomous implementation, or provides an issue title containing "#N" (e.g., "6.3.5: Feature Name #860 Epic #851"). This is the workhorse skill for turning an issue into a merged-ready PR.
argument-hint: "#issue-number [--branch name] [--epic #N]"
---

# Implement a GitHub Issue

Take a GitHub Issue through the full lifecycle: understand it, implement it, test it, ship a PR, and handle review feedback. The goal is a PR that's ready for human review — well-tested, well-described, and following every project convention.

## CRITICAL: Autonomous Execution

**This is a fully autonomous workflow. Do NOT stop between phases.** Execute all phases (1 → 2 → 2.5 → 3 → 3.5 → 4 → 5) in a single unbroken run. The user invoked this skill expecting a PR with all review feedback addressed as the final output — not intermediate summaries, not progress reports, not "what should I do next?" questions.

**Rules:**
- Do NOT summarize progress and wait for the user between phases
- Do NOT ask for confirmation before proceeding to the next phase
- Do NOT present a plan and ask if it looks good — execute it
- The ONLY reasons to pause: (1) a gate failure you cannot resolve after trying, or (2) a genuine ambiguity where two valid interpretations lead to incompatible implementations

After completing each phase, proceed **immediately** to the next one.

## Parse arguments

Extract from `$ARGUMENTS`:
- **Issue number** (required) — `#N` or bare number. If the input contains multiple `#N` references, the smaller number is typically the issue and the larger is the epic.
- **Branch name** — `--branch <name>`, or derive as `work/<issue-number>-<slug>` from the issue title
- **Epic number** — `--epic #N` for parent context, or detect from the issue's sub-issue relationships. Also look for "Epic #N" in the input.

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

**Do NOT stop here. Proceed immediately to Phase 2.**

## Phase 2: Implement

Confirm in one line: "Research complete. The issue requires [1-sentence summary]. Implementing." — then keep going.

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

### Quick self-check

Before moving to simplify, do a fast author's pass on your own diff. These are the bugs that slip through most often:

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

**Do NOT stop here. Proceed immediately to Phase 2.5.**

## Phase 2.5: Simplify

Before testing, run the `/simplify` skill to review your changed code for reuse opportunities, quality, and efficiency:

```
Skill(skill="simplify")
```

This pass catches and fixes:
- Duplicated logic that could reuse existing utilities
- Overly complex code that can be simplified
- Inefficient patterns (unnecessary loops, redundant operations)
- Code that doesn't follow adjacent patterns in the same module

`/simplify` edits code directly, so it must run before tests — tests should validate the simplified code, not the pre-simplified version.

**Do NOT stop here. Proceed immediately to Phase 3.**

## Phase 3: Test and Self-Review (parallel)

Launch Phase 3 testing and Phase 3.5 self-review **in parallel** — they are independent. Testing validates behavior; self-review validates code quality. Neither depends on the other's output.

### Phase 3 Steps: Testing

All testing must pass **before** committing. Follow these steps in order.

#### How the test infrastructure works

Before running tests, understand the commands (see `src/protean/cli/test.py` and `Makefile`):

- **`protean test`** (CORE) — runs `pytest --cache-clear --ignore=tests/support/` with in-memory adapters. No external services needed. No coverage collected.
- **`protean test -c FULL`** — runs the full matrix first (all flags: `--slow --redis --sqlite --postgresql --message_db --elasticsearch --mssql`), then runs per-adapter suites (each database, broker, and event store) in parallel. All runs use `coverage run --parallel-mode`, and coverage is combined at the end.
- **`protean test -c COVERAGE`** — same as FULL but also generates a diff-cover HTML report comparing against `main`.
- **`make up`** — starts Docker services: Redis, Elasticsearch, PostgreSQL, MessageDB, MSSQL.
- **`make test-full`** — runs `make up` then `protean test -c FULL` (convenient shortcut).
- **`uv run pytest <files> --cov=protean --cov-report=term-missing`** — for targeted coverage on specific test files. Use `--cov-config=/dev/null` to bypass `.coveragerc` exclusions.

**Important:** Always use `uv run` when running `protean test` or `pytest` to ensure the correct virtual environment.

#### Step 1: Fast iteration on your tests

```bash
uv run pytest <your-test-file> -v --tb=short
```

Iterate until your new tests pass. Fix bugs in both production code and tests.

#### Step 2: Core tests (no adapters)

```bash
uv run protean test
```

**Gate: every core test must pass.** If any test fails, investigate and fix before proceeding. Do not skip or ignore failures — they indicate either a regression in your code or a pre-existing issue that must be understood.

#### Step 3: Code quality checks

Run all quality checks in parallel:

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/protean
```

If ruff reports fixable issues, auto-fix them: `uv run ruff check --fix src/ tests/ && uv run ruff format src/ tests/`. For mypy, only fix errors introduced by your changes — pre-existing errors are not your responsibility.

#### Step 4: Full suite with adapters (if Docker is available)

```bash
make test-full
```

This starts Docker services and runs the full test suite with all adapter configurations. If Docker is not available or services fail to start, note this limitation and proceed — CI will run the full matrix. Do not block on Docker availability.

#### Step 5: Coverage of new code

After `protean test -c FULL` passes, it generates `coverage.xml`. Use `diff-cover` to measure patch coverage — the coverage of lines changed on this branch compared to `main`:

```bash
uv run diff-cover coverage.xml --compare-branch=main --show-uncovered
```

This reports exactly which new/modified lines are uncovered, grouped by file. The output includes line numbers you can target directly.

**Gate: 100% patch coverage.** If any new or modified lines are uncovered:

1. Read the uncovered line numbers from the diff-cover output
2. Write tests that exercise those specific code paths
3. Re-run `uv run pytest <your-test-files> -v` to confirm the new tests pass
4. Re-run `uv run diff-cover coverage.xml --compare-branch=main` to verify coverage improved

Repeat until patch coverage reaches 100%. If a line is genuinely untestable (e.g., a defensive branch that can't be triggered), note it in the PR description — but this should be rare. If `coverage.xml` is unavailable (Docker not running), use targeted coverage instead:

```bash
uv run pytest <your-test-files> --cov=protean --cov-report=term-missing --cov-config=/dev/null -v
```

#### Testing conventions

- **No mocks.** Register real domain elements: `test_domain.register(MyAggregate)` then `test_domain.init(traverse=False)`.
- **Tests ship with code.** Same commit, same PR. Never a separate "add tests" step.
- **Test placement follows source layout.** `src/protean/core/aggregate.py` → `tests/aggregate/`.

### Phase 3.5 Steps: Self-Review (run in parallel with Phase 3)

Launch the `pr-reviewer` agent in the background while tests run:

```
Agent(subagent_type="pr-reviewer", prompt="Review the uncommitted changes on this branch against main. Run `git diff` to see the changes. Report blockers, suggestions, and things done well.", run_in_background=true)
```

When the reviewer completes, act on findings:

- **Blockers** — fix every one. Missing changelog entry, unmitigated breaking change, missing type hints, untested code path — these must be resolved before committing.
- **Suggestions** — use judgment. If a suggestion improves clarity or correctness, take it. If it's purely stylistic and debatable, skip it.

After fixing blockers, re-run affected tests (`uv run pytest <changed-test-files> -v`) to confirm fixes didn't break anything.

### What the reviewer catches that you'll miss as the author

These are the patterns that slip past the person who wrote the code but are obvious to a reviewer:

- Tests that loop over collections without asserting the collection is non-empty
- Docstrings that promise behavior the code doesn't deliver for all paths
- Missing auto-generation of IDs when "always present" semantics are documented
- Assertions that test implementation details rather than behavior
- New public APIs without `__init__.py` exports
- Inconsistent naming with adjacent code in the same module
- Edge cases in middleware/integrations: no domain context, no command processed, missing headers

### Pre-commit checklist

Before proceeding to Phase 4, verify **all** of these are true:

- [ ] `/simplify` has been run (Phase 2.5)
- [ ] New tests pass (`uv run pytest <test-file> -v`)
- [ ] Core suite passes (`uv run protean test`)
- [ ] Quality checks pass (ruff lint, ruff format, mypy — no new errors)
- [ ] Self-review blockers resolved (Phase 3.5)
- [ ] No conflict markers in any file

If any item is incomplete, complete it now. **Do NOT stop here. Proceed immediately to Phase 4.**

## Phase 4: Commit and PR

### Rebase against main before committing

Main may have advanced while you were implementing. Rebase to avoid merge conflicts in the PR:

```bash
git fetch origin main
git rebase origin/main
```

If the rebase introduces conflicts, resolve them and re-run `uv run pytest <your-test-file> -v` to verify the resolution is correct.

### Add changelog entry

Read `CHANGELOG.md` and add an entry under `[Unreleased]` in the appropriate subsection (Added, Changed, Fixed, etc.). Write from the user's perspective — what changed for them, not what files were edited.

### Check for breaking changes

If your diff renames, removes, or changes behavior of anything in `protean.*` that user code could depend on:

- **Tier 1 (surface — renamed/moved)**: Add a deprecation wrapper that delegates to the new implementation
- **Tier 2 (behavioral — same API, different behavior)**: Flag to user — needs a config flag
- **Tier 3 (structural — persistence format, event schema)**: Flag to user — needs migration docs

Don't proceed silently with unmitigated breaks.

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

### Check mergeability

After the PR is created, verify it's mergeable:

```bash
gh pr view <PR_NUMBER> -R proteanhq/protean --json mergeable,mergeStateStatus,statusCheckRollup
```

If the branch has conflicts with `main`, rebase and force-push:

```bash
git fetch origin main
git rebase origin/main
git push --force-with-lease
```

If CI checks are failing, investigate and fix before moving to Phase 5.

**Do NOT stop here. Proceed immediately to Phase 5.**

## Phase 5: Handle review feedback and coverage

After creating the PR, wait for CI checks (Copilot review, Codecov coverage report) to arrive. Poll until both are available:

```bash
# Check for review comments (Copilot typically arrives in 2-5 minutes)
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments --jq 'length'

# Check CI status including Codecov
gh pr checks <PR_NUMBER> -R proteanhq/protean
```

Check every 60 seconds, up to 10 minutes. While waiting, you may proceed with other independent work if available.

### Check Codecov patch coverage

**Codecov is the authoritative source for coverage**, not local measurements. Codecov runs in CI with the full matrix of adapters and may report different numbers than local `diff-cover`. Once CI completes, Codecov posts a comment on the PR with patch coverage. Fetch it:

```bash
gh api repos/proteanhq/protean/issues/<PR_NUMBER>/comments --jq '.[] | select(.user.login == "codecov[bot]" or .user.login == "codecov-commenter") | .body'
```

If patch coverage is below 100%:

1. Read the Codecov comment to identify uncovered files and lines
2. Write tests targeting those specific uncovered paths
3. Run `uv run pytest <new-test-files> -v` to confirm they pass
4. Commit and push: `git add <files> && git commit -m "Add tests to improve patch coverage" && git push`
5. Wait for Codecov to re-run and verify patch coverage improved

Repeat until Codecov reports 100% patch coverage. If a line is genuinely untestable, note it in the PR description.

### Fetch and address review comments

Once Copilot comments arrive:

```bash
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments --jq '.[] | {id, path, body, line, in_reply_to_id}'
```

For each top-level comment (`in_reply_to_id` is null):

- **Agree and fix** — the comment identifies a real issue. Fix the code.
- **Disagree** — the comment misunderstands a project convention. Prepare a reasoned reply.
- **Out of scope** — acknowledge and explain.

### Common Copilot catches to preempt

These are the patterns Copilot flags most often on this project — catching them in self-review (Phase 3.5) saves a round trip:

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

Reply to each comment using the correct API path for PR review comment replies:

```bash
gh api repos/proteanhq/protean/pulls/<PR_NUMBER>/comments/<COMMENT_ID>/replies \
  -f body='Fixed — one sentence explaining the change.'
```

### Re-check mergeability

After pushing review fixes, verify the PR is still mergeable:

```bash
gh pr view <PR_NUMBER> -R proteanhq/protean --json mergeable,mergeStateStatus,statusCheckRollup
```

If conflicts appeared (e.g., `main` advanced while addressing feedback), rebase and force-push:

```bash
git fetch origin main
git rebase origin/main
git push --force-with-lease
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
- Patch coverage: N% (diff-cover)

Review:
- N comments addressed, all threads resolved
- PR is mergeable, CI checks passing
```

Never merge the PR — leave that to the user.
