# Chapter 5: Testing the Ledger

We have been running code manually in scripts and the Protean shell. It
is time for proper automated tests. In this chapter we will discover
Protean's testing DSL — a fluent API that reads like English: "given an
Account after these events, process this command."

## The Testing DSL

Protean provides a `given()` function that starts a test sentence:

```python
from protean.testing import given
```

The DSL chains three concepts:

1. **`given(Aggregate, ...events)`** — set up aggregate history
2. **`.process(Command)`** — dispatch a command through the full pipeline
3. **Assert** the result — `.accepted`, `.rejected`, `.events`, etc.

## Setting Up Tests

Create a `conftest.py` that initializes the domain:

```python
--8<-- "guides/getting-started/es-tutorial/ch05.py:conftest"
```

And create reusable event fixtures:

```python
--8<-- "guides/getting-started/es-tutorial/ch05.py:fixtures"
```

## Testing Account Creation

When no prior events exist, use `given(Account)` with no event
arguments:

```python
--8<-- "guides/getting-started/es-tutorial/ch05.py:test_create"
```

Key assertions:

- **`result.accepted`** — the command was processed successfully.
- **`AccountOpened in result.events`** — the `EventLog` supports `in`
  for type checking.
- **`result.events[AccountOpened]`** — access the event instance by
  type.
- **`result.holder_name`** — the result proxies attribute access to the
  aggregate, so you can check final state directly.

## Testing with History

When an account already exists, seed the event store with prior events:

```python
--8<-- "guides/getting-started/es-tutorial/ch05.py:test_deposit"
```

`given(Account, account_opened)` tells the DSL: "create an Account by
replaying this event, then process the command." The command handler
loads the aggregate (which now has a $1,000 balance from the
`AccountOpened` event), calls `deposit()`, and persists.

## Testing Rejections

When a command violates a business rule, use `.rejected`:

```python
--8<-- "guides/getting-started/es-tutorial/ch05.py:test_rejection"
```

- **`result.rejected`** — the command was rejected (a `ValidationError`
  was raised).
- **`result.rejection_messages`** — a flat list of error strings from
  the `ValidationError`.
- **`len(result.events) == 0`** — no events were recorded because the
  command was rejected.

## Multi-Command Chaining

Test an entire lifecycle by chaining `.process()` calls:

```python
--8<-- "guides/getting-started/es-tutorial/ch05.py:test_lifecycle"
```

Each `.process()` builds on the state left by the previous one.
`.events` always reflects the **last** command, while `.all_events`
accumulates events across **all** chained commands.

## Testing Invariant Violations

Verify that the "cannot close with balance" invariant works:

```python
--8<-- "guides/getting-started/es-tutorial/ch05.py:test_close_rejection"
```

## Running the Tests

```shell
$ pytest test_fidelis.py -v
test_fidelis.py::test_open_account PASSED
test_fidelis.py::test_deposit_increases_balance PASSED
test_fidelis.py::test_overdraft_is_rejected PASSED
test_fidelis.py::test_full_account_lifecycle PASSED
test_fidelis.py::test_cannot_close_with_balance PASSED

5 passed in 0.12s
```

## Why Integration Tests?

Notice that `given().process()` runs the **full pipeline**: it calls
`domain.process()`, which routes to the command handler, which loads the
aggregate from the event store, calls the domain method, persists the
result, and returns. There are no mocks.

This is deliberate. Event-sourced systems derive their state from events
— mocking the event store would defeat the purpose. The testing DSL
makes integration tests fast enough (in-memory) and expressive enough
(fluent API) that you rarely need unit tests with mocks.

## What We Built

- **`given(Account)`** for testing creation commands.
- **`given(Account, event1, event2)`** for testing with prior history.
- **`.process(Command)`** to dispatch through the full pipeline.
- **`.accepted`** and **`.rejected`** for asserting outcomes.
- **`EventLog`** with `in`, `[]`, `.types`, `.first`, `.last`.
- **Multi-command chaining** with `.process().process()`.
- **`.all_events`** for cross-command event accumulation.
- **`.rejection_messages`** for flat error string access.

Part I is complete. We have a solid banking ledger with business rules
and comprehensive tests. In Part II, we will grow the platform with
projections, event handlers, async processing, and cross-aggregate
coordination.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch05.py:full"
```

## Next

[Chapter 6: The Account Dashboard →](06-account-dashboard.md)
