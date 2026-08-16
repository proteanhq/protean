# `protean eventstore dlq`

The `protean eventstore dlq` command group shows the event store's
dead-letter queue: the positions a subscription retried up to `max_retries`
and then gave up on. Those give-ups are recorded as `Exhausted` records in
each subscription's internal `failed-*` stream. `list` enumerates the
exhausted positions per subscription; `inspect` re-reads the failing event so
you can see what could not be processed.

This is different from [`protean dlq`](./dlq.md). `protean dlq` manages the
**broker** dead-letter queue (messages a broker subscription failed and moved
to `{stream_category}:dlq`). `protean eventstore dlq` covers **event-store**
subscriptions (event handlers, command handlers, projectors), which do not use
a broker DLQ; they track failed positions and, on exhaustion, leave the event
in place in the store.

All commands accept a `--domain` option for the domain module path (defaults to
the current directory) and a `--json` flag for the shared CLI result envelope.

## Commands

| Command | Description |
|---------|-------------|
| `protean eventstore dlq list` | List exhausted positions, grouped by subscription |
| `protean eventstore dlq inspect` | Re-read the failing event behind an exhausted position |

## `protean eventstore dlq list`

Lists the exhausted positions across all event-store subscriptions, or a single
one filtered by stream category.

```bash
# All subscriptions
protean eventstore dlq list --domain=my_domain

# One subscription (by stream category)
protean eventstore dlq list --subscription=order --domain=my_domain

# Machine-readable JSON
protean eventstore dlq list --domain=my_domain --json
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--subscription` | Filter by stream category (e.g. `order`) | All subscriptions |
| `--json` | Output the result envelope instead of a table | `False` |

**Output**

```
                    Exhausted positions — my_domain
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Handler                       ┃ Stream Category ┃ Exhausted Positions ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ app.handlers.OrderHandler     │ order           │ 42, 87              │
└───────────────────────────────┴─────────────────┴─────────────────────┘

2 exhausted position(s) across 1 subscription(s).
```

A subscription with no exhausted positions is not shown. When nothing is
exhausted anywhere, the command prints `No exhausted positions.` and exits `0`.

Under `--json` the result is the shared result envelope, with the
per-subscription list under `data.subscriptions`:

```json
{
  "version": "0.1.0",
  "status": "pass",
  "data": {
    "subscriptions": [
      {
        "handler": "app.handlers.OrderHandler",
        "stream_category": "order",
        "exhausted": [42, 87]
      }
    ]
  },
  "diagnostics": []
}
```

## `protean eventstore dlq inspect`

Re-reads the event behind an exhausted position and prints its type, global
position, and data. The event is read live from the store (it is never copied
into the exhausted record), so you always see its current form.

```bash
protean eventstore dlq inspect 42 --domain=my_domain

# Machine-readable JSON
protean eventstore dlq inspect 42 --domain=my_domain --json
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `POSITION` | Exhausted global position (positional argument) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--subscription` | Stream category to search in | All subscriptions |
| `--json` | Output the result envelope instead of text | `False` |

Under `--json` the envelope's `data` carries `position`, `type`,
`global_position`, and `data`:

```json
{
  "version": "0.1.0",
  "status": "pass",
  "data": {
    "position": 42,
    "type": "MyDomain.OrderPlaced.v1",
    "global_position": 42,
    "data": { "order_id": "abc", "total": 100 }
  },
  "diagnostics": []
}
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success (including "no exhausted positions") |
| `2` | Usage/environment error: unloadable domain, unknown `--subscription`, unknown position, or an event that can no longer be re-read |

## Error handling

| Condition | Behavior |
|-----------|----------|
| Invalid domain path | Error envelope (with `--json`) or "Error loading Protean domain", exit `2` |
| `--subscription` matches no event-store subscription | "No event-store subscription found for stream category ...", exit `2` |
| `inspect` position is not exhausted | "No exhausted position ... found", exit `2` |
| `inspect` event can no longer be read | "Could not re-read the event ...", exit `2` |

## How positions get exhausted

When an event-store handler raises, the subscription records the failed
position and retries it on each recovery pass. After `max_retries` retries it
writes an `Exhausted` record and stops retrying. The record carries the failing
event's `stream_name` and `stream_position` so `inspect` can locate the event;
records written before this was added fall back to the origin stream, read by
global position.

For the full error-handling guide, see
[Error Handling](../../../guides/server/error-handling.md). For subscription
lifecycle details, see
[Subscriptions](../../../concepts/async-processing/subscriptions.md).

## Domain discovery

The `protean eventstore dlq` commands use the same domain discovery mechanism
as other CLI commands. See [Domain Discovery](../project/discovery.md) for the
full resolution logic.
