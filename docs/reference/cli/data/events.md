# `protean events`

The `protean events` command group provides tools for inspecting the event
store. These commands help you read events from streams, view statistics
across aggregates, search for specific event types, and display the full
event history of an aggregate instance -- all without writing custom scripts.

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

## Commands

| Command | Description |
|---------|-------------|
| `protean events read` | Read and display events from a stream |
| `protean events stats` | Show stream statistics across the domain |
| `protean events search` | Search for events by type across streams |
| `protean events history` | Display the event timeline for an aggregate instance |
| `protean events trace` | Follow the full causal chain for a correlation ID |

## `protean events read`

Reads events from a specific stream (entity stream or category stream) and
displays them in a formatted table.

```bash
# Read from an entity stream
protean events read "test::user-abc123" --domain=my_domain

# Read from a category stream (all events for an aggregate type)
protean events read "test::user" --domain=my_domain

# Read from a specific position with a limit
protean events read "test::user-abc123" --from 5 --limit 10 --domain=my_domain

# Include full event data payloads
protean events read "test::user-abc123" --data --domain=my_domain

# Include correlation and causation IDs
protean events read "test::user-abc123" --trace --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `STREAM` | Stream name (positional argument) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--from` | Start reading from this position | `0` |
| `--limit` | Maximum number of events to display | `20` |
| `--data/--no-data` | Show full event data payloads | `--no-data` |
| `--trace/--no-trace` | Show correlation and causation ID columns | `--no-trace` |

**Output**

```
┏━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Position ┃ Global Pos ┃ Type                    ┃ Time                ┃ Data Keys   ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│        0 │          1 │ App.UserRegistered.v1   │ 2026-02-22 10:30:00 │ name, email │
│        1 │          5 │ App.UserEmailChanged.v1 │ 2026-02-22 10:31:00 │ email       │
└──────────┴────────────┴─────────────────────────┴─────────────────────┴─────────────┘

Showing 2 event(s) from position 0
```

## `protean events stats`

Displays aggregate-level statistics: instance counts, event counts, and the
most recent event per aggregate.

```bash
protean events stats --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |

**Output**

```
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Aggregate ┃ Stream Category ┃ ES? ┃ Instances ┃ Events ┃ Latest Type           ┃ Latest Time         ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ User      │ app::user       │ Yes │        15 │     47 │ App.UserUpdated.v1    │ 2026-02-22 10:30:00 │
│ Order     │ app::order      │ No  │         8 │     23 │ App.OrderPlaced.v1    │ 2026-02-22 09:15:00 │
└───────────┴─────────────────┴─────┴───────────┴────────┴───────────────────────┴─────────────────────┘

Total: 70 event(s) across 23 aggregate instance(s)
```

The **ES?** column indicates whether the aggregate is configured as
event-sourced (`is_event_sourced=True`).

## `protean events search`

Searches for events matching a type name. Supports both exact and partial
matching.

```bash
# Partial match (case-insensitive substring match)
protean events search --type=UserRegistered --domain=my_domain

# Exact match (when type contains dots)
protean events search --type=App.UserRegistered.v1 --domain=my_domain

# Restrict to a specific stream category
protean events search --type=UserRegistered --category=app::user --domain=my_domain

# Limit results and show data
protean events search --type=UserRegistered --limit=5 --data --domain=my_domain

# Include trace IDs
protean events search --type=UserRegistered --trace --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--type` | Event type to search for | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--category` | Restrict search to a stream category | All streams (`$all`) |
| `--limit` | Maximum number of results to display | `20` |
| `--data/--no-data` | Show full event data payloads | `--no-data` |
| `--trace/--no-trace` | Show correlation and causation ID columns | `--no-trace` |

**Type matching rules:**

- If the search term contains dots (e.g., `App.UserRegistered.v1`), an
  **exact match** is performed against the event type.
- Otherwise, a **case-insensitive substring match** is used, so `User`
  matches `App.UserRegistered.v1`, `App.UserUpdated.v1`, etc.

## `protean events history`

Displays the full event timeline for a specific aggregate instance, including
snapshot information when available.

```bash
# Show event timeline
protean events history --aggregate=User --id=abc-123 --domain=my_domain

# Include full event data
protean events history --aggregate=User --id=abc-123 --data --domain=my_domain

# Include trace IDs
protean events history --aggregate=User --id=abc-123 --trace --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--aggregate` | Aggregate class name (e.g. `User`) | Required |
| `--id` | Aggregate instance identifier | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--data/--no-data` | Show full event data payloads | `--no-data` |
| `--trace/--no-trace` | Show correlation and causation ID columns | `--no-trace` |

**Output**

```
         User (abc-123)
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ Version ┃ Type                    ┃ Time                ┃ Data Keys   ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│       0 │ App.UserRegistered.v1   │ 2026-02-22 10:30:00 │ name, email │
│       1 │ App.UserEmailChanged.v1 │ 2026-02-22 10:31:00 │ email       │
│       2 │ App.UserDeactivated.v1  │ 2026-02-22 10:32:00 │ reason      │
└─────────┴─────────────────────────┴─────────────────────┴─────────────┘
Snapshot exists at version 1

User (abc-123): 3 event(s), current version: 2
```

## `protean events trace`

Follows the full causal chain for a given `correlation_id`. Scans all events
in the event store that share the same correlation ID and displays them in
chronological order, revealing the complete causation tree of a business
operation.

```bash
# Follow a causal chain
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" --domain=my_domain

# Include full event data payloads
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" --data --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `CORRELATION_ID` | Correlation ID to trace (positional argument) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--data/--no-data` | Show full event data payloads | `--no-data` |

**Output**

The output shows the stream, type, time, correlation ID, and causation ID for
each message in the chain. When `--data` is enabled, event payloads are
displayed inline.

```
Trace: a1b2c3d4... (3 messages)
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Stream                    ┃ Type                    ┃ Time                ┃ Causation ID              ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ app::order:command-abc123 │ App.PlaceOrder.v1       │ 2026-02-22 10:30:00 │                           │
│ app::order-abc123         │ App.OrderPlaced.v1      │ 2026-02-22 10:30:01 │ app::order:command-abc123 │
│ app::inventory-inv456     │ App.InventoryReserved.v1│ 2026-02-22 10:30:02 │ app::order-abc123-0.1     │
└───────────────────────────┴─────────────────────────┴─────────────────────┴───────────────────────────┘
```

This is useful for debugging multi-step workflows and verifying that trace
context propagates correctly across handlers.

See [Message Tracing](../../../guides/domain-behavior/message-tracing.md) for
details on how correlation and causation IDs work.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Invalid domain path | Aborts with "Error loading Protean domain" |
| Aggregate not found in registry (`history`) | Aborts with "not found in domain" |
| No events in stream (`read`) | Prints "No events found in stream" |
| No matching events (`search`) | Prints "No events found matching type" |
| No events for aggregate (`history`) | Prints "No events found for \<Aggregate\>" |
| No aggregates in domain (`stats`) | Prints "No aggregates registered" |
| No events for correlation ID (`trace`) | Prints "No events found for correlation ID" |

## Domain Discovery

The `protean events` commands use the same domain discovery mechanism as
other CLI commands. The `--domain` option accepts:

- A Python module path: `my_package.domain`
- A file path: `src/my_domain.py`
- A module with instance name: `my_domain:custom_domain`
- `.` (default): Searches the current directory

See [Domain Discovery](../project/discovery.md) for the full resolution logic.
