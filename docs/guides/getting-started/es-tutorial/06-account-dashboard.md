# Chapter 6: The Account Dashboard

The product team needs a customer-facing dashboard showing account
summaries — current balance, transaction count, last activity. Reading
this from the event store by replaying events every time is not
practical. In this chapter we will build a **projection** — a
denormalized, read-optimized view — and a **projector** that keeps it
up to date automatically as events occur.

## The Write Model vs. Read Model

Our `Account` aggregate is the **write model** — it enforces business
rules and records events. But querying it requires replaying events from
the event store, which gets expensive as the history grows.

A **projection** is a **read model** — a flat, query-optimized table
designed for a specific view. The projector listens to events and
updates the projection automatically.

## Defining the Projection

```python
--8<-- "guides/getting-started/es-tutorial/ch06.py:projection"
```

Notice:

- Projections use basic field types only — no `HasMany`, no
  `ValueObject`. They are flat database tables.
- **`identifier=True`** marks the projection's primary key.
- The projection stores exactly the data the dashboard needs.

## Defining the Projector

```python
--8<-- "guides/getting-started/es-tutorial/ch06.py:projector"
```

Key concepts:

- **`projector_for=AccountSummary`** links this projector to its
  projection.
- **`aggregates=[Account]`** tells the projector which event streams
  to subscribe to.
- **`@on(EventType)`** maps each event to a handler method — an alias
  for `@handle` that reads better in projector context.
- Each handler loads, updates, and saves the projection through a
  repository.

!!! tip "Projections are Mutable"
    Unlike events (which are immutable facts), projections are
    mutable views. The projector loads, modifies, and saves them on
    every event — always overwriting with the latest derived state.

## Trying It Out

```python
--8<-- "guides/getting-started/es-tutorial/ch06.py:usage"
```

```shell
$ python fidelis.py
Account: Alice Johnson (ACC-001)
Balance: $1500.00

Dashboard:
  Balance: $1500.00
  Transactions: 1
```

The projection was updated automatically by the projector as events
flowed through the system.

## What We Built

- An **AccountSummary** projection — a flat, query-optimized read model.
- An **AccountSummaryProjector** that listens to account events and
  updates the projection.
- The **`@on` decorator** for mapping events to projector handlers.
- **`domain.view_for()`** — the read-only view API for querying
  projections (with `get()`, `query`, `find_by()`, `count()`, `exists()`).
- A clear separation between the **write model** (aggregate) and
  **read model** (projection).

In the next chapter, we will add event handlers for side effects like
compliance alerts and notifications — reactions that do not update a
projection but trigger external actions.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch06.py:full"
```

## Next

[Chapter 7: Reacting to Events →](07-reacting-to-events.md)
