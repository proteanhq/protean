# Chapter 2: Deposits and Withdrawals

An account that can only be opened is not very useful. In this chapter
we will add deposits and withdrawals — multiple event types flowing
through a single aggregate. Along the way, we will see a core principle
of Event Sourcing: **all state changes flow exclusively through events**.

## New Events

A deposit and a withdrawal are two distinct facts:

```python
--8<-- "guides/getting-started/es-tutorial/ch02.py:deposit_withdrawal_events"
```

Each event captures the data needed to describe what happened. The
`reference` field is optional — it records why the transaction occurred
(a paycheck, a refund, a grocery purchase).

## Domain Methods and Apply Handlers

Now we add domain methods to the `Account` aggregate and the
corresponding `@apply` handlers:

```python
--8<-- "guides/getting-started/es-tutorial/ch02.py:aggregate"
```

Notice the separation of concerns:

- **Domain methods** (`deposit()`, `withdraw()`) contain **validation
  logic** — they check that the amount is positive and that funds are
  sufficient. If validation passes, they call `raise_()`.
- **`@apply` handlers** contain **pure state mutations** — they update
  the balance. No validation, no side effects, just state changes.

This separation is critical. During replay (when loading from the event
store), only the `@apply` handlers run. The validation in `deposit()`
and `withdraw()` does not re-execute — those events already happened and
were validated at the time. Replay trusts the event history.

## Multiple Events, One Aggregate

Let's exercise the full lifecycle:

```python
--8<-- "guides/getting-started/es-tutorial/ch02.py:main_usage"
```

Run it:

```shell
$ python fidelis.py
Account: Alice Johnson (ACC-001)
Balance: $1550.00
Version: 3
```

The balance is `$1,550.00`: the opening deposit of $1,000 plus $500
and $200 in deposits, minus the $150 withdrawal. But this number was
never stored — it was computed by replaying four events through their
`@apply` handlers.

## Version Tracking

Each event increments the aggregate's `_version`. After four events
(opened, two deposits, one withdrawal), the version is `3` (0-indexed).
The version serves as an optimistic concurrency check — if two processes
try to modify the same account simultaneously, the second one will
detect a version conflict.

## Validation at the Domain Boundary

Try withdrawing more than the balance:

```python
--8<-- "guides/getting-started/es-tutorial/ch02.py:overdraft_validation"
```

Output:

```
Rejected: {'amount': ['Insufficient funds']}
```

The validation in `withdraw()` catches the problem **before** any event
is raised. No event means no state change. The aggregate remains
consistent.

!!! note
    This validation lives in the domain method, not in the `@apply`
    handler. In the next chapters we will move business rules into
    **invariants** — a more robust mechanism that validates state
    after every `@apply` handler runs.

## What We Built

- **DepositMade** and **WithdrawalMade** events describing financial
  transactions.
- Domain methods that **validate** inputs and **raise events**.
- `@apply` handlers that **mutate state** from events.
- An aggregate that derives its balance from **multiple events**.
- **Version tracking** that increments with each event.

The aggregate is starting to feel like a real ledger. Next, we will add
commands and the processing pipeline so external systems can interact
with our domain through typed contracts.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch02.py:full"
```

## Next

[Chapter 3: Commands and the Processing Pipeline →](03-commands-and-pipeline.md)
