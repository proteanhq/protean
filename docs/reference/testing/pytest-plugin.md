# Pytest Plugin

Auto-registered via the `pytest11` entry point — installed alongside
Protean. No `conftest.py` registration required.

For task-oriented workflow guidance see
[Dual-Mode Testing](../../guides/testing/index.md#dual-mode-testing) for
switching environments via `--protean-env`, and
[Fixtures and Patterns](../../guides/testing/fixtures-and-patterns.md)
for `DomainFixture` and `conftest.py` recipes.

## CLI options

| Option | Default | Effect |
|---|---|---|
| `--protean-env=<name>` | `test` | Sets `PROTEAN_ENV` before test collection, so the matching `[<name>]` overlay in `domain.toml` applies when the domain is constructed at import time. |
| `--update-snapshots` | off | Causes `assert_snapshot()` calls to regenerate their reference files instead of comparing. |

## Registered markers

The plugin registers these markers so `--strict-markers` accepts them
without configuration:

| Marker | Intent |
|---|---|
| `domain` | Pure domain logic tests — no database |
| `application` | Command/event handler tests — uses database |
| `integration` | Cross-aggregate tests with real adapters |
| `slow` | Tests taking more than a second or two |
| `bdd` | Behavior-driven scenarios |

Markers are tags for filtering with `-m`; they do not change test
behavior on their own.

## Protean's own `test_domain` fixture

The session-scoped autouse `test_domain` fixture described in some
Protean test suites is defined in
`protean.integrations.pytest.adapter_conformance` and is **not**
auto-loaded by this plugin. It activates only when a `conftest.py`
opts in explicitly:

```python
pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]
```

When opted in, tests that construct their own `Domain(name="Test")`
should add `@pytest.mark.no_test_domain` so the session fixture is
skipped for that test.

User application tests should construct their domain lifecycle with
`DomainFixture` instead — see
[Fixtures and Patterns](../../guides/testing/fixtures-and-patterns.md).

## Framework development

The `protean test` CLI command is used to run Protean's own test suite
across adapter configurations. It is not intended for user
applications. See
[Testing Protean](../../community/contributing/testing.md) for details.
