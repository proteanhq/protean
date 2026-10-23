# Chapter 19: The Great Migration, Run on Priority Lanes

Fidelis acquires another bank and must migrate 2 million historical
accounts. Running all 2 million `OpenAccount` commands through the
normal pipeline would starve real-time production traffic, deposits and
withdrawals from existing customers would queue behind millions of migration
events.

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

- **Primary**: `fidelis::account`, production traffic
- **Backfill**: `fidelis::account:backfill`, bulk/migration traffic

The `StreamSubscription` always drains the primary stream first. Backfill
events are processed only when the primary is empty.

## The Priority Enum

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch19.py:priority_enum"
```

Events with priority **below the threshold** (default: 0) are routed to
the backfill stream. Everything else goes to the primary stream.

## Running the Migration

Wrap bulk operations in the `processing_priority()` context manager:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch19.py:migrate_legacy_accounts"
```

All commands within the `processing_priority(Priority.BULK)` context
are routed to the backfill stream. Production traffic continues flowing
through the primary stream at full speed.

## Nested Priorities

Contexts nest. The innermost wins:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch19.py:nested_priorities"
```

## Per-Command Priority

You can also set priority on individual commands:

```python
# fragment
--8<-- "guides/getting-started/es-tutorial/ch19.py:per_command_priority"
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
3. If primary is empty → **one blocking read on both streams** (1s
   max)
4. Process the primary messages from that read, then the backfill
   messages, and go to step 1

Production traffic always takes precedence. The backfill stream is only
touched when production is idle.

## What We Built

- **Priority lanes** with primary and backfill streams.
- **`processing_priority(Priority.BULK)`** context manager for bulk
  operations.
- **Per-command priority** with `domain.process(..., priority=...)`.
- **Nested priority contexts** for mixed workloads.
- Production traffic isolation during large migrations.

That completes Part IV. The platform now has fact
events, message tracing, DLQ management, monitoring, and priority lanes.
In Part V, we achieve mastery over the complete system.

## Full Source

??? example "ch19.py, 278 lines"

    ```python
    --8<-- "guides/getting-started/es-tutorial/ch19.py:full"
    ```

## Next

[Chapter 20: Rebuilding the World →](20-rebuilding-projections.md)
