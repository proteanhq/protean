# Chapter 11: Testing Your Domain

In this chapter we will set up pytest for Bookshelf and write tests that
verify our business logic, commands, events, invariants, projections, and API
endpoints.

!!! tip "Focus on business logic"
    Protean handles field validation, immutability, and wiring automatically.
    Your tests should focus on the behavior *you* wrote, invariants, state
    transitions, command flows, and event reactions. For a deeper discussion,
    see [Testing](../../testing/index.md).

## Setting Up Tests

Protean ships with a pytest plugin and `DomainFixture` that handles
initialization, context management, and cleanup. Create a `conftest.py`:

```python
--8<-- "guides/getting-started/tutorial/tests/conftest.py:full"
```

`DomainFixture.setup()` calls `domain.init()` to discover and wire all
domain elements, and creates database schema if needed. The `_ctx`
fixture activates the domain context for each test and resets all data
on exit. Inside your tests, use `current_domain` to access the active
domain.

## Testing Aggregates and Invariants

Test the business rules *you* wrote, invariants, state guards, and meaningful
state transitions:

```python
--8<-- "guides/getting-started/tutorial/tests/test_invariants.py:full"
```

### Testing Value Objects

Value object tests should focus on domain behavior, equality semantics and any
custom logic:

```python
--8<-- "guides/getting-started/tutorial/tests/test_value_objects.py:full"
```

## Testing Commands and Handlers

Test the full command processing flow. The `_ctx` fixture ensures
`current_domain` is available:

```python
--8<-- "guides/getting-started/tutorial/tests/test_commands.py:full"
```

## Testing Events and Event Handlers

Verify that events trigger the expected reactions:

```python
--8<-- "guides/getting-started/tutorial/tests/test_events.py:full"
```

## Testing Projections

Verify that projectors maintain projections correctly using
`domain.view_for()`:

```python
--8<-- "guides/getting-started/tutorial/tests/test_projections.py:full"
```

## Testing API Endpoints

Test the FastAPI endpoints using `TestClient`:

```python
--8<-- "guides/getting-started/tutorial/tests/test_api.py:full"
```

## Integration Testing

Test complete flows from command to final state:

```python
--8<-- "guides/getting-started/tutorial/tests/test_integration.py:full"
```

## Running Tests

Run the tests:

```shell
$ pytest -v
```

All tests use in-memory adapters by default, no Docker, no database setup, no
manual cleanup. For testing against real infrastructure, see the [Testing
guide](../../testing/index.md) and the [Dual-Mode
Testing](../../../patterns/dual-mode-testing.md) pattern.

## What We Built

- **Test fixtures** with `DomainFixture` for automatic setup and teardown.
- **Invariant tests** for business rules and state guards.
- **Command flow tests** from dispatch to persisted state.
- **Event handler tests** verifying automatic side effects.
- **Projection tests** confirming projector output using `domain.view_for()`.
- **API endpoint tests** using FastAPI's `TestClient`.
- An **integration test** covering a complete end-to-end flow.

That completes Part II. We have a fully tested bookstore with a
web API, a real database, and organized code. In the next chapter, we will move
to asynchronous processing so the system can handle real production traffic.

## Next

[Chapter 12: Going Async with the Server →](12-going-async.md)
