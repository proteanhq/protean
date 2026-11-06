# Pytest Plugin

Protean installs this plugin and registers it with pytest through the
`pytest11` entry point. You do not need to register it in `conftest.py`.

To switch environments via `--protean-env`, see
[Dual-Mode Testing](../../guides/testing/index.md#run-the-same-tests-in-two-modes).
For `DomainFixture` and `conftest.py` recipes, see
[Fixtures and Patterns](../../guides/testing/fixtures-and-patterns.md).

## Which CLI options does the plugin add?

| Option | Default | Effect |
|---|---|---|
| `--protean-env=<name>` | `test` | Sets `PROTEAN_ENV` before test collection, unless the shell already set it, so the matching `[<name>]` overlay in `domain.toml` applies when the domain is constructed at import time. |
| `--update-snapshots` | off | Causes `assert_snapshot()` calls to regenerate their reference files instead of comparing. |

## Which markers does the plugin register?

The plugin registers these markers so `--strict-markers` accepts them
without configuration:

| Marker | Intent |
|---|---|
| `domain` | Pure domain logic tests, no database |
| `application` | Command/event handler tests, uses database |
| `integration` | Cross-aggregate tests with real adapters |
| `slow` | Tests taking more than a second or two |
| `bdd` | Behavior-driven scenarios |

Markers are tags for filtering with `-m`. They do not change test behavior on
their own.

## Protean's own `test_domain` fixture

The autouse `test_domain` fixture described in some Protean test suites is
defined in `protean.integrations.pytest.adapter_conformance` and is **not**
auto-loaded by this plugin. It is function-scoped: every test gets a fresh,
initialized domain, unless the test carries `@pytest.mark.no_test_domain`. It
activates only when your root `conftest.py` opts in explicitly:

```python
# fragment
--8<-- "reference/testing/pytest-plugin/opt_in/conftest.py:opt_in"
```

When opted in, tests that construct their own `Domain(name="Test")`
should add `@pytest.mark.no_test_domain`. The fixture then yields `None`
for that test instead of building a domain:

```python
# fragment
--8<-- "reference/testing/pytest-plugin/opt_in/test_opt_in.py:tests"
```

User application tests should construct their domain lifecycle with
`DomainFixture` instead, see [Fixtures and
Patterns](../../guides/testing/fixtures-and-patterns.md).

## Assert query count and shape in tests

Four context managers observe the SQL a block issues against a SQLAlchemy
backend, to catch query-cost regressions in tests. Three of them assert query
count and shape. `capture_queries` yields the raw statements for custom
assertions such as insert ordering. They are no-ops when no SQLAlchemy engine
is resolved (e.g. the in-memory adapter). See [Test Query
Shape](../../guides/testing/query-shape-tests.md) for usage.

::: protean.integrations.pytest.assert_query_count
    options:
      show_root_heading: true
      show_source: false

::: protean.integrations.pytest.assert_no_subquery_wrap
    options:
      show_root_heading: true
      show_source: false

::: protean.integrations.pytest.assert_no_overfetch
    options:
      show_root_heading: true
      show_source: false

::: protean.integrations.pytest.capture_queries
    options:
      show_root_heading: true
      show_source: false

## Run Protean's own test suite

Protean's contributors use the `protean test` CLI command to run Protean's own
test suite across adapter configurations. It is not intended for user
applications. See [Testing Protean](../../community/contributing/testing.md)
for details.
