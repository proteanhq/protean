# Chapter 19: The Great Migration — Priority Lanes

Fidelis acquires another bank and must migrate 2 million historical
accounts. Running all 2 million `OpenAccount` commands through the
normal pipeline would starve real-time production traffic — deposits and
withdrawals from existing customers would queue behind millions of
migration events.

**Priority lanes** solve this by separating production traffic from bulk
operations.

## The Problem

Without priority lanes, the migration floods the event stream:

```
Redis Stream (fidelis::account):
  [migration] [migration] [migration] [deposit] [migration] [migration] ...
```

A customer trying to deposit money waits behind thousands of migration
commands. Response times spike. The support team gets angry calls.

## Configuring Priority Lanes

Add to `domain.toml`:

```toml
[server.priority_lanes]
enabled = true
threshold = 0          # Events with priority < 0 go to backfill
backfill_suffix = "backfill"
```

With this configuration, Protean creates **two streams** per category:

- **Primary**: `fidelis::account` — production traffic
- **Backfill**: `fidelis::account:backfill` — bulk/migration traffic

The `StreamSubscription` always drains the primary stream first. Backfill
events are processed only when the primary is empty.

## The Priority Enum

```python
from protean.utils.processing import Priority

# Priority.BULK     = -100
# Priority.LOW      = -50
# Priority.NORMAL   =  0   (default)
# Priority.HIGH     =  50
# Priority.CRITICAL =  100
```

Events with priority **below the threshold** (default: 0) are routed to
the backfill stream. Everything else goes to the primary stream.

## Running the Migration

Wrap bulk operations in the `processing_priority()` context manager:

```python
from protean.utils.processing import processing_priority, Priority


def migrate_legacy_accounts(legacy_accounts: list[dict]) -> None:
    with processing_priority(Priority.BULK):
        for i, legacy in enumerate(legacy_accounts):
            domain.process(OpenAccount(
                account_number=legacy["number"],
                holder_name=legacy["name"],
                opening_deposit=legacy["balance"],
            ))
            if i % 10_000 == 0:
                print(f"Migrated {i:,} accounts...")

    print(f"Migration complete: {len(legacy_accounts):,} accounts queued.")
```

All commands within the `processing_priority(Priority.BULK)` context
are routed to the backfill stream. Production traffic continues flowing
through the primary stream at full speed.

## Nested Priorities

Contexts nest — the innermost wins:

```python
with processing_priority(Priority.BULK):
    # These go to backfill stream
    domain.process(OpenAccount(account_number="MIGR-001", ...))

    # But a critical real-time deposit still goes to primary
    with processing_priority(Priority.CRITICAL):
        domain.process(MakeDeposit(account_id="acc-vip", amount=1_000_000))

    # Back to BULK for remaining migration
    domain.process(OpenAccount(account_number="MIGR-002", ...))
```

## Per-Command Priority

You can also set priority on individual commands:

```python
domain.process(
    OpenAccount(account_number="MIGR-001", ...),
    priority=Priority.BULK,
)
```

## Monitoring the Migration

Track backfill progress with the CLI:

```shell
$ protean subscriptions status --domain=fidelis
 Handler                     Type    Stream                Lag     Pending  DLQ  Status
 AccountCommandHandler       stream  fidelis::account:cmd      0        0    -  ok
 AccountCommandHandler       stream  fidelis::...:backfill   450K       10    -  ok
 AccountSummaryProjector     stream  fidelis::account          0        0    -  ok
 AccountSummaryProjector     stream  fidelis::...:backfill   450K        0    -  ok
```

The backfill lag decreases over hours as the server processes migration
events during quiet periods.

## How the Engine Processes

The `StreamSubscription` polling cycle:

1. **Read from primary stream** (non-blocking)
2. If messages found → process them, go to step 1
3. If primary is empty → **read from backfill stream** (blocking, 1s
   max)
4. If backfill messages found → process them, go to step 1
5. If both empty → wait and repeat

Production traffic always takes precedence. The backfill stream is only
touched when production is idle.

## What We Built

- **Priority lanes** with primary and backfill streams.
- **`processing_priority(Priority.BULK)`** context manager for bulk
  operations.
- **Per-command priority** with `domain.process(..., priority=...)`.
- **Nested priority contexts** for mixed workloads.
- Production traffic isolation during large migrations.

Part IV is complete. We have a production-grade platform with fact
events, message tracing, DLQ management, monitoring, and priority lanes.
In Part V, we achieve mastery over the complete system.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch19.py:full"
```

## Next

[Chapter 20: Rebuilding the World →](20-rebuilding-projections.md)
