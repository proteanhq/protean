# Testing DSL

Test helpers for domains, exported from `protean.testing`. The `given` function
is the entry point for most tests: it drives the full command pipeline (command
to handler to aggregate to events) and returns a result you assert against.

The [testing guide](../guides/testing/event-sourcing-tests.md) shows how these
helpers fit together. The [pytest plugin
reference](../reference/testing/pytest-plugin.md) lists the fixtures that set
up a domain.

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

`given(...)` and the helpers below return these result objects. Each result
object holds the events, state and errors produced. A test asserts against that
one object and does not need to inspect the domain directly.

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

In a test, asynchronous processing has no fixed point at which the work is
finished. `drain` and `process_and_wait` run the engine until it is idle. A
test then needs no sleep for a guessed duration. Prefer them to a bare `sleep`.
A bare `sleep` is the single most common cause of a test that passes locally
and flakes in CI.

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
