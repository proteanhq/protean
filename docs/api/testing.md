# Testing DSL

Fluent test helpers for event-sourced aggregates. The `given` function
provides a Pythonic DSL for integration tests that exercise the full command
processing pipeline: command -> handler -> aggregate -> events.

See [Testing guide](../guides/testing/event-sourcing-tests.md) for
practical usage.

::: protean.testing
    options:
      show_root_heading: false
      members:
        - given
        - AggregateResult
        - EventLog
      filters: []
