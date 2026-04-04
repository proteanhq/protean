# Implement Skill — Reference

Read during Phase 1. Internalize and keep moving.

## Test infrastructure

| Command | What it does |
|---------|-------------|
| `uv run protean test` | Core tests, in-memory adapters, no Docker |
| `uv run protean test -c FULL` | Full matrix with coverage (all adapters, parallel) |
| `make up` | Start Docker: Redis, ES, PostgreSQL, MessageDB, MSSQL |
| `make test-full` | `make up` + `protean test -c FULL` |
| `uv run diff-cover coverage.xml --compare-branch=main --show-uncovered` | Patch coverage |
| `uv run pytest <files> --cov=protean --cov-report=term-missing --cov-config=/dev/null` | Targeted coverage |

Always prefix with `uv run`.

## Test conventions

- **No mocks.** Use `test_domain.register(MyAggregate)` then `test_domain.init(traverse=False)`.
- **Tests ship with code.** Same commit, same PR.
- **Placement follows source:** `src/protean/core/aggregate.py` → `tests/aggregate/`.
- **`test_domain` fixture** creates domain named "Test" — stream prefixes are `test::`.
- **Fact events require opt-in:** aggregate must have `fact_events=True`.
- **Stream name format:** `{domain_name}::{stream}`, e.g. `test::user-fact-v1`.
- **Assert non-empty before looping:**
  ```python
  assert len(events) > 0, "Expected events but got none"
  for event in events:
      assert event.correlation_id is not None
  ```

## Common review findings

Catch these during the Phase 2 self-check — both the pr-reviewer agent and GitHub Copilot flag them:

- Docstrings that promise behavior not delivered for all code paths
- Test loops over empty collections (assertions pass vacuously)
- Missing ID auto-generation when "always present" semantics are documented
- Assertions testing implementation details rather than behavior
- New public APIs without `__init__.py` exports
- Inconsistent naming with adjacent code in the same module
- Missing edge cases in middleware: no domain context, no command processed, missing headers

## Phase 5: CI feedback commands

**Poll for comments and CI status:**
```bash
# Comment count (Copilot typically arrives in 2-5 minutes)
gh api repos/proteanhq/protean/pulls/<PR>/comments --jq 'length'

# CI check status
gh pr checks <PR> -R proteanhq/protean
```

**Fetch Codecov report:**
```bash
gh api repos/proteanhq/protean/issues/<PR>/comments \
  --jq '.[] | select(.user.login == "codecov[bot]" or .user.login == "codecov-commenter") | .body'
```

**Fetch Copilot review comments:**
```bash
gh api repos/proteanhq/protean/pulls/<PR>/comments \
  --jq '.[] | {id, path, body, line, in_reply_to_id}'
```

**Reply to a review comment:**
```bash
gh api repos/proteanhq/protean/pulls/<PR>/comments/<COMMENT_ID>/replies \
  -f body='Fixed — one sentence explaining the change.'
```

**Check mergeability:**
```bash
gh pr view <PR> -R proteanhq/protean --json mergeable,mergeStateStatus,statusCheckRollup
```

## Commit message rules

- Start with a verb: Add, Fix, Update, Remove, Refactor
- No AI attribution, no session links, no "Co-Authored-By"
- Don't override git user config

## Breaking change tiers

- **Tier 1 (surface — renamed/moved):** Deprecation wrapper delegating to new implementation
- **Tier 2 (behavioral — same API, different behavior):** Config flag, defaulting to old behavior
- **Tier 3 (structural — persistence/schema):** Version the schema, migration docs
