# Chapter 21: The Event Store as a Database

We have been working with events through aggregates, projections, and
handlers for the entire tutorial. But we have never looked at the event
store directly. In this chapter we will explore it as a database —
reading raw events, viewing statistics, searching by type, and
understanding the stream naming conventions.

## Reading Events from a Stream

View events for a specific account:

```shell
$ protean events read "fidelis::account-acc-001" --domain=fidelis
 Position  Global Pos  Type              Time                Data Keys
 0         1           AccountOpened      2025-01-10 09:15   account_id, account_number, holder_name, opening_deposit
 1         5           DepositMade        2025-01-10 10:30   account_id, amount, source_type, reference
 2         12          DepositMade        2025-02-01 14:00   account_id, amount, source_type, reference
 3         18          WithdrawalMade     2025-03-01 09:00   account_id, amount, reference

Showing 4 event(s) from position 0
```

Add `--data` to see full payloads:

```shell
$ protean events read "fidelis::account-acc-001" --data --domain=fidelis
```

Use `--from` and `--limit` for pagination:

```shell
$ protean events read "fidelis::account-acc-001" --from=10 --limit=5 --domain=fidelis
```

## Reading Category Streams

Omit the instance ID to read across all accounts:

```shell
$ protean events read "fidelis::account" --limit=10 --domain=fidelis
```

This returns events from all account instances, ordered by
`global_position`.

## Stream Naming Conventions

| Stream | Pattern | Example |
|--------|---------|---------|
| Instance stream | `{domain}::{category}-{id}` | `fidelis::account-acc-001` |
| Category stream | `{domain}::{category}` | `fidelis::account` |
| Command stream | `{domain}::{category}:command-{id}` | `fidelis::account:command-acc-001` |
| Snapshot stream | `{domain}::{category}:snapshot-{id}` | `fidelis::account:snapshot-acc-001` |
| Fact event stream | `{domain}::{category}-fact-{id}` | `fidelis::account-fact-acc-001` |

The stream category is derived from the aggregate's class name
(lowercased, underscored).

## Domain-Wide Statistics

```shell
$ protean events stats --domain=fidelis
 Aggregate   Stream Category      ES?  Instances  Events  Latest Type         Latest Time
 Account     fidelis::account     Yes     1,247  245,891  DepositMade         2025-06-16 15:30
 Transfer    fidelis::transfer    Yes       312    1,248  TransferCompleted   2025-06-16 14:55

Total: 247,139 event(s) across 1,559 aggregate instance(s)
```

This gives you a high-level view of the entire event store: how many
aggregates, how many events, and the latest activity.

## Searching by Event Type

Find all events of a specific type:

```shell
$ protean events search --type=DepositMade --domain=fidelis
 Position  Global Pos  Type         Stream                        Time
 1         5           DepositMade  fidelis::account-acc-001      2025-01-10 10:30
 2         12          DepositMade  fidelis::account-acc-001      2025-02-01 14:00
 ...

Found 89,234 event(s) matching type 'DepositMade' (showing first 20)
```

Searches support partial matching and are case-insensitive:

```shell
$ protean events search --type=deposit --domain=fidelis
```

## Event Store Positions

Two position numbers appear in event listings:

- **Position** — the event's index within its specific stream
  (0-indexed). This is the aggregate's version number.
- **Global Position** — a monotonically increasing counter across the
  **entire** event store. This establishes a total ordering of all
  events, regardless of which aggregate they belong to.

Global position is critical for projection rebuilding (events must be
replayed in global order) and for subscription position tracking.

## Memory vs. MessageDB

Throughout this tutorial we used the **memory event store** — great for
development and testing, but not persistent across restarts.

For production, use **MessageDB** — a PostgreSQL-based event store:

```toml
# domain.toml (production)
[event_store]
provider = "message_db"
database_uri = "${MESSAGE_DB_URL|postgresql://message_store@localhost:5432/message_store}"
```

MessageDB provides:

- Persistent storage with PostgreSQL durability
- Optimistic concurrency control
- Efficient category reads and stream queries
- SQL access for ad-hoc analysis

The domain code does not change — only the configuration.

## What We Built

- **`protean events read`** for reading raw events from streams.
- **`protean events stats`** for domain-wide statistics.
- **`protean events search`** for finding events by type.
- Understanding of **stream naming conventions**.
- Understanding of **position** vs. **global position**.
- **Memory** vs. **MessageDB** event store adapters.

The event store is not just an implementation detail — it is a database
of facts about your business. Learning to query it directly is a
powerful debugging and analysis tool.

## Next

[Chapter 22: The Full Picture →](22-the-full-picture.md)
