---
applyTo: "tests/**"
---

# Testing Review Guidelines

## Core principles

- **Avoid mocks** unless truly necessary. Test against real in-memory adapters.
- Every PR that changes behavior must include tests. Tests ship with code, never as separate PRs.
- Test all adapter implementations — don't test only the memory adapter when adding cross-adapter features.

## Test placement

Tests mirror source structure:

| Source | Tests |
|--------|-------|
| `src/protean/core/<element>.py` | `tests/<element>/` |
| `src/protean/adapters/` | `tests/adapters/` |
| `src/protean/cli/` | `tests/cli/` |
| `src/protean/server/` | `tests/server/` |
| `src/protean/utils/` | `tests/utils/` |

Flag any test file that mixes concerns from unrelated source modules.

## Domain fixture pattern

Tests must use the `test_domain` autouse fixture and call `init(traverse=False)`:

```python
def test_something(test_domain):
    test_domain.register(MyAggregate)
    test_domain.init(traverse=False)  # Always traverse=False in tests
```

If a test creates its own `Domain(name="Test")`, it must be marked `@pytest.mark.no_test_domain`.

## Markers

- Infrastructure-dependent tests must use appropriate markers: `@pytest.mark.postgresql`, `@pytest.mark.redis`, `@pytest.mark.elasticsearch`, `@pytest.mark.sqlite`, `@pytest.mark.message_db`.
- Broker tests use capability-tier markers (`basic_pubsub`, `simple_queuing`, `reliable_messaging`, `ordered_messaging`, `enterprise_streaming`).
- Slow tests must be marked `@pytest.mark.slow`.

## Common issues to flag

- Missing `traverse=False` in `test_domain.init()` calls.
- Tests that import from `tests/support/` without proper setup (support tests are excluded from collection).
- Shared domain element definitions duplicated inline instead of placed in an `elements.py` file (each test directory may have an `elements.py` for domain elements shared across its test files).
- Mock overuse when in-memory adapters would suffice.
- Missing markers on tests that require external services.
