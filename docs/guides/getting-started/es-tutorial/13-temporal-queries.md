# Chapter 13: Looking Back in Time

A regulatory inquiry arrives: "What was account ACC-7742's balance on
March 15th at 4:00 PM?" This is not about the current balance — it is
about the balance at a specific moment in the past.

Event Sourcing makes this possible. Because we have the complete event
history, we can reconstruct the aggregate at **any historical point**.

## Querying by Version

Use `at_version` to reconstruct the aggregate after a specific event:

```python
with domain.domain_context():
    repo = domain.repository_for(Account)

    # What was the state after the 5th event?
    account_v5 = repo.get("acc-7742", at_version=5)
    print(f"Balance at version 5: ${account_v5.balance:.2f}")
```

Versions are 0-indexed. `at_version=0` gives you the state after the
first event (the creation event). `at_version=5` gives you the state
after the sixth event.

## Querying by Timestamp

Use `as_of` to reconstruct the aggregate at a specific point in time:

```python
from datetime import datetime, timezone

march_15 = datetime(2025, 3, 15, 16, 0, tzinfo=timezone.utc)
account_march = repo.get("acc-7742", as_of=march_15)
print(f"Balance on March 15: ${account_march.balance:.2f}")
```

Protean filters events by their timestamp, including only events
written on or before the requested time.

!!! note
    `at_version` and `as_of` are **mutually exclusive**. You cannot
    use both in the same query.

## Temporal Aggregates Are Read-Only

Historical state must not be modified. Protean enforces this:

```python
try:
    account_march.raise_(DepositMade(
        account_id="acc-7742", amount=100.00
    ))
except IncorrectUsageError as e:
    print(e)
    # "Cannot raise events on a temporally-loaded aggregate..."
```

When an aggregate is loaded with `at_version` or `as_of`, it is marked
as **temporal**. Any attempt to call `raise_()` raises
`IncorrectUsageError`. This is a safety mechanism — you should never
raise new events on a historical view.

## Interaction with Snapshots

Temporal queries work with snapshots:

- **`at_version`**: If a snapshot exists before the target version,
  Protean loads the snapshot and replays only the events between the
  snapshot and the target.
- **`as_of`**: Snapshots are not used (they may contain events after
  the target timestamp). Events are replayed from the beginning.

## Exploring Event History with the CLI

The `protean events history` command shows the complete timeline for
an aggregate:

```shell
$ protean events history --aggregate=Account --id=acc-7742 --domain=fidelis
                        Account (acc-7742)
 Version  Type                      Time
 0        AccountOpened              2025-01-10 09:15:00
 1        DepositMade                2025-01-10 10:30:00
 2        DepositMade                2025-02-01 14:00:00
 3        WithdrawalMade             2025-03-01 09:00:00
 4        DepositMade                2025-03-15 11:30:00
 ...
```

Add `--data` to see full event payloads:

```shell
$ protean events history --aggregate=Account --id=acc-7742 --data --domain=fidelis
```

This is invaluable for debugging — you can see exactly what happened
to an aggregate and when.

## What We Built

- **`repo.get(id, at_version=N)`** — reconstruct at a specific version.
- **`repo.get(id, as_of=datetime)`** — reconstruct at a specific
  timestamp.
- **Read-only temporal aggregates** that prevent accidental mutations.
- **Event history CLI** for exploring an aggregate's timeline.

Temporal queries are a superpower unique to Event Sourcing. Traditional
CRUD systems cannot answer "what was the state at time T?" without
complex auditing infrastructure. With Event Sourcing, it is a one-line
query.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch13.py:full"
```

## Next

[Chapter 14: Connecting to the Outside World →](14-connecting-outside-world.md)
