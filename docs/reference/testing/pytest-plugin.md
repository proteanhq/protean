# Pytest Plugin

Protean ships with a pytest plugin that is **automatically activated** when
Protean is installed — no configuration or `conftest.py` registration needed.

## `--protean-env` Option

Control which `domain.toml` environment overlay is active during test runs:

```shell
# Default: uses [test] overlay (PROTEAN_ENV=test)
pytest

# Use [memory] overlay — in-memory adapters, no Docker needed
pytest --protean-env memory

# Use a custom overlay
pytest --protean-env staging
```

The option sets the `PROTEAN_ENV` environment variable before test collection,
so your `domain.toml` overlays determine which adapters are used:

```toml
# domain.toml
[test]
databases.default.provider = "memory"
brokers.default.provider = "inline"

[memory]
databases.default.provider = "memory"
brokers.default.provider = "inline"
event_store.provider = "memory"
```

This enables **dual-mode testing**: run the same test suite against in-memory
adapters for fast feedback during development, and against real infrastructure
for final validation in CI. No test code or fixture changes are needed — only
the adapter configuration changes.

See the [Dual-Mode Testing](../../patterns/dual-mode-testing.md) pattern for
the full setup guide.

## Automatic Fixtures

The plugin provides these fixtures automatically:

| Fixture | Scope | Description |
|---------|-------|-------------|
| `test_domain` | session | Auto-discovered domain instance, activated for the test session |

The `test_domain` fixture is an autouse session-scoped fixture. If a test
creates its own `Domain(name="Test")` instead of using this fixture, mark it
with `@pytest.mark.no_test_domain` so the fixture is skipped.

## Framework Development

The `protean test` CLI command is used to run Protean's own test suite across
adapter configurations. It is not intended for user applications. See
[Testing Protean](../../community/contributing/testing.md) for details.
