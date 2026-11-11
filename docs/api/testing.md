# Testing DSL

Test helpers for domains, exported from `protean.testing`. The `given` function
is the entry point for most tests: it drives the full command pipeline (command
to handler to aggregate to events) and returns a result you assert against.

See the [testing guide](../guides/testing/event-sourcing-tests.md) for how these
fit together, and the [pytest plugin reference](../reference/testing/pytest-plugin.md)
for the fixtures that set up a domain.

Everything on this page is in `protean.testing.__all__`. Anything not on this
page is internal, whatever its name suggests.

## Entry point

::: protean.testing
    options:
      show_root_heading: false
      members:
        - given
      filters: []

## Results

`given(...)` and the helpers below return these result objects. Each carries
the events, state and errors produced, so a test asserts against one object
instead of inspecting the domain.

::: protean.testing
    options:
      show_root_heading: false
      members:
        - AggregateResult
        - ProcessResult
        - ProcessManagerResult
        - ProjectionResult
        - EventLog
        - EventSequence
      filters: []

## Helpers

`drain` and `process_and_wait` exist because asynchronous processing has no
natural join point in a test. They run the engine until it is idle, so a test
does not sleep for a guessed duration. Prefer them to a bare `sleep`, which is
the single most common cause of a test that passes locally and flakes in CI.

!!! warning "`get_generic_test_dir` is deprecated"
    `get_generic_test_dir()` is deprecated since 0.19.0 and removed in 0.20.0.
    Each call raises `RemovedInProtean020Warning`. See
    [Adapter Conformance Testing](../reference/testing/conformance.md#port-suites-under-testsconformance).

::: protean.testing
    options:
      show_root_heading: false
      members:
        - drain
        - process_and_wait
        - assert_chain
        - assert_snapshot
        - get_generic_test_dir
      filters: []
