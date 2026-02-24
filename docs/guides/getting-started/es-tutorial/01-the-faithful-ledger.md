# Chapter 1: The Faithful Ledger

In this chapter we will create the foundation of our digital banking
platform, **Fidelis**. By the end, we will have an event-sourced
`Account` aggregate that records every state change as an immutable event
and reconstructs its balance by replaying those events.

A bank cannot simply store the current balance and overwrite it on every
transaction. Every deposit, every withdrawal is a **fact** that happened
— and facts cannot be undone. Event Sourcing captures this reality:
instead of storing state, we store the events that produced it.

## Setting Up

Create a new directory for the project and install Protean:

```shell
mkdir fidelis
cd fidelis
pip install protean
```

Create a file called `fidelis.py`. Every Protean application begins
with a **Domain**:

```python
from protean import Domain

domain = Domain("fidelis")
```

Protean ships with in-memory adapters for databases, brokers, and event
stores, so we can focus entirely on domain modeling without setting up
any infrastructure.

## Defining the AccountOpened Event

In Event Sourcing, we define what **happened** before we define the
aggregate. Our first event records the fact that an account was opened:

```python
--8<-- "guides/getting-started/es-tutorial/ch01.py:event"
```

Events are past-tense descriptions of facts. `AccountOpened` captures
everything we need to know about the account's creation: who opened it,
what number it was assigned, and how much was deposited.

## Defining the Account Aggregate

Now let's define the `Account` aggregate with `is_event_sourced=True`:

```python
--8<-- "guides/getting-started/es-tutorial/ch01.py:aggregate"
```

There is a lot happening here. Let's break it down:

- **`is_event_sourced=True`** tells Protean this aggregate derives its
  state from events, not from a database row.
- **`Account.open()`** is a class-level factory method. It calls
  `_create_new()` to create a blank aggregate with only an
  auto-generated identity, then calls `raise_()` to emit the creation
  event.
- **`raise_()`** does two things for event-sourced aggregates: it
  records the event, and it immediately calls the matching `@apply`
  handler to mutate the aggregate's state.
- **`@apply`** marks `on_account_opened` as the handler for
  `AccountOpened` events. This method is the **single source of truth**
  for how this event type changes the aggregate. It runs both during
  live operations (when `raise_()` is called) and during replay (when
  the aggregate is loaded from the event store).

!!! important "The Golden Rule"
    In an event-sourced aggregate, **never set fields directly** outside
    of `@apply` handlers. All state changes flow through `raise_()` →
    `@apply`. This guarantees that replaying events produces identical
    state.

## Creating an Account

Let's create an account and persist it:

```python
--8<-- "guides/getting-started/es-tutorial/ch01.py:usage"
```

Two important things happen:

1. **`repo.add(account)`** does not write a row to a database. It writes
   the `AccountOpened` event to the **event store** — an append-only log
   of everything that has ever happened.

2. **`repo.get(account.id)`** does not read a row. It fetches all events
   for this account from the event store and replays them through the
   `@apply` handlers to reconstruct the current state.

Run it:

```shell
$ python fidelis.py
Created: Alice Johnson (ACC-001)
ID: 5eb04301-f191-4bca-9e49-8e5a948f07f6
Balance: $1000.00

Retrieved: Alice Johnson
Balance: $1000.00
Version: 0

All checks passed!
```

The balance was not stored anywhere — it was derived from the single
`AccountOpened` event. The `_version` starts at `0`, corresponding to
the first event.

## Exploring in the Shell

Protean includes an interactive shell that pre-loads your domain:

```shell
$ protean shell --domain fidelis
```

Inside the shell, you can create accounts, make transactions, and
inspect the event store interactively:

```python
>>> account = Account.open("ACC-002", "Bob Smith", 500.00)
>>> account.balance
500.0
>>> repo = domain.repository_for(Account)
>>> repo.add(account)
>>> loaded = repo.get(account.id)
>>> loaded.balance
500.0
```

## What We Built

- A **Domain** named "fidelis" — the container for our banking logic.
- An **AccountOpened** event describing the fact of account creation.
- An event-sourced **Account** aggregate with an `@apply` handler.
- A factory method that uses `_create_new()` and `raise_()`.
- **Persisted** the account by writing events and **retrieved** it by
  replaying them.

All of this ran in-memory with no infrastructure. In the next chapter,
we will add deposits and withdrawals — multiple events flowing through
a single aggregate.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch01.py:full"
```

## Next

[Chapter 2: Deposits and Withdrawals →](02-deposits-and-withdrawals.md)
