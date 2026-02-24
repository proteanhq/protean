# Chapter 3: Commands and the Processing Pipeline

Calling `account.deposit()` directly works for in-process code, but
external APIs need a clear contract. In this chapter we will introduce
**commands** — typed data objects that represent the intent to do
something — and **command handlers** that receive those commands, load
the aggregate from the event store, call the appropriate domain method,
and persist the result.

## Defining Commands

Commands are imperative: they describe what we want to happen.

```python
--8<-- "guides/getting-started/es-tutorial/ch03.py:commands"
```

Notice the naming convention:

- **Commands** use imperative verbs: `OpenAccount`, `MakeDeposit`,
  `MakeWithdrawal`.
- **Events** (from the previous chapter) use past tense: `AccountOpened`,
  `DepositMade`, `WithdrawalMade`.

Commands express **intent** ("I want to make a deposit"). Events express
**facts** ("A deposit was made"). This distinction matters — a command
can be rejected, but an event is an immutable record of something that
already happened.

Each command is linked to an aggregate via `part_of=Account`. This tells
Protean which aggregate the command targets.

## The Command Handler

A command handler receives commands and orchestrates the work:

```python
--8<-- "guides/getting-started/es-tutorial/ch03.py:command_handler"
```

The command handler follows a consistent pattern:

1. **Load** the aggregate from the repository (or create a new one)
2. **Call** the domain method with data from the command
3. **Save** the aggregate back to the repository

The handler is a thin coordinator — it does not contain business logic.
Business logic lives in the aggregate (the `deposit()` and `withdraw()`
methods we wrote in Chapter 2).

!!! tip "current_domain"
    `current_domain` is a thread-local reference to the active domain.
    Inside handlers, it gives you access to repositories and other
    domain services without passing the domain around explicitly.

## Processing Commands

The `domain.process()` method ties everything together:

```python
--8<-- "guides/getting-started/es-tutorial/ch03.py:usage"
```

Run it:

```shell
$ python fidelis.py
Account opened: 5eb04301-f191-4bca-9e49-8e5a948f07f6
Account: Alice Johnson
Balance: $1350.00

All checks passed!
```

## How It Works

When you call `domain.process(OpenAccount(...))`, Protean:

1. Looks up the registered command handler for `OpenAccount`'s
   `part_of` aggregate (`Account`)
2. Calls the matching `@handle(OpenAccount)` method
3. The handler creates the aggregate, raises events, and persists it
4. Events are written to the event store
5. The command handler's return value is returned to the caller

For now we configure synchronous processing:

```python
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"
```

In Chapter 8, we will switch to asynchronous processing where commands
flow through a message broker.

## Stream Categories

Behind the scenes, events are organized into **streams**. Each
aggregate instance has its own stream:

- `fidelis::account-{id}` — events for a specific account
- `fidelis::account` — the category stream containing all account events

Commands are dispatched through a command stream:

- `fidelis::account:command-{id}` — commands for a specific account

Stream categories are derived from the aggregate's class name. You
rarely need to think about them, but they become important when
configuring subscriptions in Chapter 8.

## What We Built

- **Commands** (`OpenAccount`, `MakeDeposit`, `MakeWithdrawal`) that
  express intent with typed fields.
- A **Command Handler** that follows the load-mutate-save pattern.
- The **`domain.process()`** pipeline that routes commands to handlers.
- Synchronous processing for development.

The domain now has a clean external contract: submit a command, and
the system handles the rest. Next, we will add business rules that
protect the aggregate from invalid state transitions.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch03.py:full"
```

## Next

[Chapter 4: Business Rules That Never Break →](04-business-rules.md)
