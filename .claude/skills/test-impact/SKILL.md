---
name: test-impact
description: Identify and run only the tests affected by current code changes. Use when the user says "run affected tests", "test my changes", "what tests should I run", "smart test", or wants a fast feedback loop after editing source files. More targeted than /test — this skill maps changed files to their test counterparts instead of running everything. Also use when the user says "did I break anything" after editing a specific module.
---

# Smart Test Selector

Map changed source files to the tests that exercise them, then run only those tests. The goal is fast feedback — catch the most likely regressions without waiting for the full suite.

## Collect changed files

Gather changes from two sources — the branch (committed work) and the working tree (uncommitted edits):

```bash
git diff --name-only main...HEAD -- 'src/'
git diff --name-only -- 'src/'
```

Combine and deduplicate. If only test files changed (no `src/` changes), run those test files directly and skip the mapping step.

## Map source files to test paths

The project follows a consistent convention for where tests live:

| Source path | Test path | Notes |
|-------------|-----------|-------|
| `src/protean/core/<element>.py` | `tests/<element>/` | e.g., `core/aggregate.py` → `tests/aggregate/` |
| `src/protean/cli/` | `tests/cli/` | |
| `src/protean/domain/` | `tests/domain/` | |
| `src/protean/server/` | `tests/server/` | |
| `src/protean/adapters/` | `tests/adapters/` | See adapter warning below |
| `src/protean/port/` | `tests/adapters/` | Ports tested through their adapters |
| `src/protean/integrations/pytest/` | `tests/integrations/pytest/` | |
| `src/protean/utils/` | `tests/utils/` | |
| `src/protean/fields/` | `tests/fields/` | |
| `src/protean/ir/` | `tests/ir/` | |
| `src/protean/ext/` | `tests/ext/` | |

Apply the mapping for each changed source file. When the test path is a directory, include the entire directory. When a source file has no obvious mapping (e.g., a new utility module), fall back to searching for test files that import from it:

```bash
grep -rl "from protean.utils.new_module" tests/ --include="*.py"
```

Verify each mapped test path actually exists before adding it to the run list — the mapping table covers the common cases, but source files may predate their tests.

## Adapter and port changes

If any changed files are under `src/protean/adapters/` or `src/protean/port/`, emit a warning after running the in-memory tests:

> Adapter/port changes detected. In-memory tests ran above, but full adapter coverage requires Docker services. Run `protean test -c FULL` to test all adapter implementations.

This is a warning, not a blocker — the in-memory tests still provide value as a fast first pass.

## Run the tests

Combine all mapped test paths into a single pytest invocation:

```bash
uv run pytest tests/aggregate/ tests/domain/ -v --tb=short
```

Do not use `--timeout` — it is not supported in this project.

If the collected test paths are empty (changed source files with no matching tests), report the gap explicitly rather than running nothing silently.

## Report

```
Source changes:
  src/protean/core/aggregate.py
  src/protean/core/entity.py

Test selection:
  tests/aggregate/  (convention: core/<element>.py → tests/<element>/)
  tests/entity/     (convention: core/<element>.py → tests/<element>/)

Results: 47 passed in 8.2s

Coverage gaps:
  (none)
```

If all tests pass, suggest running `/test` for the full core suite as a confidence check before committing.

If tests fail, report the failures but don't attempt fixes — that's the `/test` skill's job. The purpose of this skill is fast, targeted feedback, not repair.
