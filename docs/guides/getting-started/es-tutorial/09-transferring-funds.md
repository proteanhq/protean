# Chapter 9: Transferring Funds

The product team wants account-to-account transfers. This is not a
single-aggregate operation — it involves debiting one account and
crediting another. If the debit succeeds but the credit fails, we
have inconsistent state.

In this chapter we will introduce a **process manager** — a stateful
coordinator that orchestrates multi-step workflows across aggregates
using events and commands.

## Why Not a Single Transaction?

In DDD, each aggregate is a transaction boundary. You cannot modify
two aggregates in the same transaction. A funds transfer must:

1. Debit the source account
2. Credit the destination account
3. Handle failures (reverse the debit if the credit fails)

A process manager coordinates these steps through events and commands,
maintaining eventual consistency.

## The Transfer Aggregate

First, we define a `Transfer` aggregate to represent the transfer
itself:

```python
--8<-- "guides/getting-started/es-tutorial/ch09.py:transfer_events"
```

```python
--8<-- "guides/getting-started/es-tutorial/ch09.py:transfer_aggregate"
```

The transfer tracks its own lifecycle: INITIATED → COMPLETED or FAILED.

## The Process Manager

The `FundsTransferPM` process manager listens to events from both
the Transfer and Account streams and coordinates the flow:

```python
--8<-- "guides/getting-started/es-tutorial/ch09.py:process_manager"
```

Key concepts:

- **`@handle(TransferInitiated, start=True, correlate="transfer_id")`**
  — `start=True` means "create a new PM instance when this event
  arrives." The `correlate` parameter maps the event to the PM
  instance.
- **`correlate="transfer_id"`** on subsequent events routes them to
  the correct PM instance based on the transfer ID.
- Each handler can issue commands via `current_domain.process()` to
  trigger work in other aggregates.
- **`mark_as_complete()`** ends the process — no further events will
  be processed for this instance.

## The Flow

```
InitiateTransfer (command)
    └── TransferInitiated (event)
            └── PM: on_transfer_initiated()
                    └── MakeWithdrawal (command to source account)
                            └── WithdrawalMade (event)
                                    └── PM: on_source_debited()
                                            └── MakeDeposit (command to dest)
                                                    └── DepositMade (event)
                                                            └── PM: on_dest_credited()
                                                                    └── CompleteTransfer
                                                                            └── TransferCompleted
```

If the withdrawal fails (insufficient funds):

```
MakeWithdrawal (command)
    └── ValidationError
            └── FailTransfer (command)
                    └── TransferFailed (event)
```

## Process Manager State

Process managers are themselves event-sourced. Their state changes are
persisted as **transition events** in the event store. When the server
restarts, PM instances are reconstituted from their transition events,
just like aggregates.

## What We Built

- A **Transfer** aggregate with its own event stream.
- A **FundsTransferPM** process manager that coordinates the
  multi-step transfer workflow.
- **Cross-aggregate coordination** through events and commands.
- **`start=True`** and **`correlate=`** for PM lifecycle management.
- **`mark_as_complete()`** for process termination.
- Failure handling that reverses partial operations.

Process managers are the event-sourcing answer to distributed
transactions. They maintain eventual consistency without distributed
locks.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch09.py:full"
```

## Next

[Chapter 10: Entities Inside Aggregates →](10-entities-inside-aggregates.md)
