# `protean dlq`

The `protean dlq` command group provides tools for managing dead letter
queues (DLQs). When messages fail processing after exhausting retries,
they are moved to DLQ streams. These commands let you list, inspect,
replay, and purge those failed messages — both from the terminal and
via the [Observatory dashboard](../runtime/observatory.md).

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

## Commands

| Command | Description |
|---------|-------------|
| `protean dlq list` | List failed messages across DLQ streams |
| `protean dlq inspect` | Show full details of a DLQ message |
| `protean dlq replay` | Replay a single message back to its original stream |
| `protean dlq replay-all` | Replay all DLQ messages for a subscription |
| `protean dlq purge` | Purge all DLQ messages for a subscription |

## `protean dlq list`

Lists failed messages across all DLQ streams, or filtered by subscription.

```bash
# List all DLQ messages
protean dlq list --domain=my_domain

# Filter by subscription (stream category)
protean dlq list --subscription=order --domain=my_domain

# Limit results
protean dlq list --limit=50 --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--subscription` | Filter by stream category (e.g. `order`) | All subscriptions |
| `--limit` | Maximum number of messages to show | `100` |

**Output**

```
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓
┃ DLQ ID             ┃ Subscription ┃ Consumer Group          ┃ Failure Reason        ┃ Failed At           ┃ Retries ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩
│ 1708768400000-0    │ order        │ app.handlers.OrderHa... │ max_retries_exceeded  │ 2026-02-23 10:00:00 │       3 │
│ 1708768500000-0    │ payment      │ app.handlers.Payment... │ max_retries_exceeded  │ 2026-02-23 10:01:40 │       3 │
└────────────────────┴──────────────┴─────────────────────────┴───────────────────────┴─────────────────────┴─────────┘

2 DLQ message(s) found.
```

## `protean dlq inspect`

Displays the full details of a specific DLQ message, including its
complete payload.

```bash
protean dlq inspect "1708768400000-0" --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `DLQ_ID` | DLQ entry identifier (positional argument) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--subscription` | Stream category to search in | All subscriptions |

## `protean dlq replay`

Replays a single DLQ message back to its original stream for
reprocessing. The message is removed from the DLQ and published as a new
message on the target stream.

```bash
protean dlq replay "1708768400000-0" --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `DLQ_ID` | DLQ entry identifier (positional argument) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--subscription` | Stream category to search in | All subscriptions |

## `protean dlq replay-all`

Replays all DLQ messages for a given subscription back to the original
stream. This is a bulk operation — use with caution.

```bash
# Interactive (prompts for confirmation)
protean dlq replay-all --subscription=order --domain=my_domain

# Skip confirmation
protean dlq replay-all --subscription=order --yes --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--subscription` | Stream category (required) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--yes` / `-y` | Skip confirmation prompt | `False` |

## `protean dlq purge`

Permanently removes all DLQ messages for a subscription. **This cannot
be undone.**

```bash
# Interactive (prompts for confirmation)
protean dlq purge --subscription=order --domain=my_domain

# Skip confirmation
protean dlq purge --subscription=order --yes --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--subscription` | Stream category (required) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--yes` / `-y` | Skip confirmation prompt | `False` |

## Observatory Dashboard

In addition to the CLI, the [Observatory dashboard](../runtime/observatory.md)
provides a **DLQ tab** for visual management:

- **List** — View all DLQ messages with subscription filter
- **Inspect** — Click any message to view its full payload
- **Replay** — Replay individual messages or all messages for a subscription
- **Purge** — Clear all DLQ messages for a subscription

The DLQ tab auto-refreshes every 5 seconds alongside other dashboard panels.

## Observatory REST API

The Observatory exposes DLQ management endpoints for programmatic access:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dlq` | GET | List DLQ messages (`?subscription=...&limit=...`) |
| `/api/dlq/{dlq_id}` | GET | Inspect a single DLQ message |
| `/api/dlq/{dlq_id}/replay` | POST | Replay a single message |
| `/api/dlq/replay-all` | POST | Replay all messages (`?subscription=...`) |
| `/api/dlq` | DELETE | Purge all messages (`?subscription=...`) |

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Invalid domain path | Aborts with "Error loading Protean domain" |
| No default broker configured | Aborts with "No default broker configured" |
| Broker doesn't support DLQ | Aborts with "does not support dead letter queues" |
| Subscription not found | Aborts with "No subscription found for stream category" |
| DLQ message not found (`inspect`, `replay`) | Aborts with "not found" |
| No DLQ messages (`list`) | Prints "No DLQ messages found" |

## How Messages Enter the DLQ

Messages are moved to the DLQ when they fail processing after exhausting
all retry attempts. The engine's
[StreamSubscription](../../server/subscription-types.md) tracks retry counts
per message and moves messages to `{stream_category}:dlq` streams after
`max_retries` failures.

See [Subscriptions](../../../concepts/async-processing/subscriptions.md) for
details on subscription lifecycle and error handling.

## Domain Discovery

The `protean dlq` commands use the same domain discovery mechanism as
other CLI commands. See [Domain Discovery](../project/discovery.md) for the
full resolution logic.
