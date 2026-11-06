# Chapter 1: The Faithful Ledger

In this chapter you build the first part of **Fidelis**, a digital banking
platform. You end with an event-sourced `Account` aggregate that records every
state change as an immutable event. The aggregate reconstructs its balance by
replaying those events.

A bank cannot store the current balance and overwrite it on every transaction.
Every deposit and every withdrawal is a **fact** that happened. A fact cannot
be undone. With Event Sourcing, you store the events that produced the state
instead of storing the state itself.

## Setting Up

Create a new directory for the project. Then install Protean in it:

```shell
mkdir fidelis
cd fidelis
pip install protean
```

Create a file called `fidelis.py`. Every Protean application begins
with a **Domain**:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch01.py:domain"
```

Protean ships with in-memory adapters for databases, brokers, and event
stores, so we can focus entirely on domain modeling without setting up
any infrastructure.

## Defining the AccountOpened Event

In Event Sourcing, we define what **happened** before we define the
aggregate. Our first event records the fact that an account was opened:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch01.py:event"
```

Events are past-tense descriptions of facts. `AccountOpened` captures
everything we need to know about the account's creation: who opened it,
what number it was assigned, and how much was deposited.

## Defining the Account Aggregate

Now let's define the `Account` aggregate with `event_sourced=True`:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch01.py:aggregate"
```

There is a lot happening here. Let's break it down:

- **`event_sourced=True`** tells Protean this aggregate derives its
  state from events, not from a database row.
- **`Account.open()`** is a class-level factory method. It calls
  `_create_new()` to create a blank aggregate with only an
  auto-generated identity, then calls `raise_()` to emit the creation
  event.
- For event-sourced aggregates, **`raise_()`** records the event. It then
  immediately calls the matching `@apply` handler to mutate the aggregate's
  state.
- **`@apply`** marks `on_account_opened` as the handler for
  `AccountOpened` events. This method is the **single source of truth** for how
  this event type changes the aggregate. The handler runs during live
  operations, when `raise_()` is called. It also runs during replay, when the
  aggregate is loaded from the event store.

!!! important "The Golden Rule"
    In an event-sourced aggregate, **never set fields directly** outside of
    `@apply` handlers. Every state change starts with a call to `raise_()`,
    which then calls the `@apply` handler. This guarantees that replaying
    events produces identical state.

## Creating an Account

The code below creates an account, persists it, and loads it back from the
repository:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch01.py:usage"
```

The repository does not write or read database rows here:

1. **`repo.add(account)`** does not write a row to a database. It writes
   the `AccountOpened` event to the **event store**. An append-only log of
   everything that has ever happened.

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

The balance was not stored anywhere. It was derived from the single
`AccountOpened` event. The `_version` starts at `0`, corresponding to the first
event.

## Exploring in the Shell

Protean includes an interactive shell that pre-loads your domain:

```shell
$ protean shell --domain fidelis
```

Inside the shell, you can create accounts, make transactions, and
inspect the event store interactively:

```pycon
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

- A **Domain** named "fidelis", the container for our banking logic.
- An **AccountOpened** event describing the fact of account creation.
- An event-sourced **Account** aggregate with an `@apply` handler.
- A factory method that uses `_create_new()` and `raise_()`.
- **Persisted** the account by writing events. **Retrieved** the account by
  replaying those events.

All of this ran in-memory with no infrastructure. In the next chapter,
we will add deposits and withdrawals, multiple events flowing through a single
aggregate.

## Full Source

??? example "ch01.py, 81 lines"

    ```python
    --8<-- "guides/getting-started/es-tutorial/ch01.py:full"
    ```

## Next

[Chapter 2: Deposits and Withdrawals →](02-deposits-and-withdrawals.md)
