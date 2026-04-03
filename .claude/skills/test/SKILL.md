---
name: test
description: Run the Protean framework test suite, diagnose failures, and fix them. Use this skill whenever the user says "run tests", "test this", "check if tests pass", "fix failing tests", wants to verify code changes, or mentions test configurations like DATABASE, BROKER, EVENTSTORE, FULL, or COVERAGE. Also trigger when the user asks to test a specific file or module, even if they don't say the word "test" explicitly — e.g., "make sure the aggregate changes work" or "verify the server didn't break".
argument-hint: "[test-path-or-pattern] [-c CONFIG]"
---

# Run Protean Tests

Run the test suite, understand any failures, and fix them. The goal is to leave the codebase with passing tests.

## Choosing the right command

Look at `$ARGUMENTS` to decide what to run:

**No arguments** — run the core in-memory suite:
```bash
uv run protean test
```

**A configuration flag** like `-c FULL`, `-c DATABASE`, `-c BROKER`, `-c EVENTSTORE`, `-c COVERAGE`:
```bash
uv run protean test -c <CONFIG>
```
The `-c FULL` config starts Docker services and tests all adapter implementations. The others test specific adapter categories.

**A file or directory path** like `tests/aggregate/` or `tests/server/test_engine.py`:
```bash
uv run pytest <path> -v --tb=short
```

**A path with a specific test** like `tests/aggregate/test_lifecycle.py::TestAggregateLifecycle::test_create`:
```bash
uv run pytest <path>::<class>::<test> -v --tb=short
```

**A keyword filter** — if the user describes a test by name rather than path:
```bash
uv run pytest -k "keyword" -v --tb=short
```

Important: the `--timeout` flag is not supported — don't use it.

## When tests fail

Resist the urge to immediately start changing code. First understand what actually went wrong:

1. **Read the full pytest output** — identify every failing test and its traceback. Multiple failures may share a root cause.

2. **Trace the failure to its source** — read both the test file and the source code it exercises. The test name and the import paths in the traceback tell you where to look. Tests live in `tests/` organized by feature, and source lives in `src/protean/`.

3. **Decide what's wrong** — is the test expectation outdated (test bug), or did a source change break behavior (source bug)? If a recent edit caused the failure, the source is likely the problem. If the test was testing old behavior that intentionally changed, update the test.

4. **Fix the root cause** — make the minimal change needed. Prefer fixing source over weakening tests, unless the test expectation is genuinely wrong.

5. **Re-run just the failing tests** to confirm:
```bash
uv run pytest <path/to/failing_test.py>::<TestClass>::<test_method> -v --tb=short
```

6. **Run the original command again** to make sure the fix didn't break anything else.

If you hit a cascade of failures (more than 5-6), stop and report what you're seeing rather than trying to fix everything at once — it likely points to a deeper issue worth discussing.

## When tests pass

Report briefly: how many tests ran, all passed, and roughly how long it took. No need for a detailed breakdown when everything is green.
