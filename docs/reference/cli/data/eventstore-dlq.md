# `protean eventstore dlq`

The `protean eventstore dlq` command group manages the event store's
dead-letter queue: the positions a subscription retried up to `max_retries`
and then gave up on. Those give-ups are recorded as `Exhausted` records in
each subscription's internal `failed-*` stream. `list` enumerates the
exhausted positions per subscription; `inspect` re-reads the failing event so
you can see what could not be processed; `replay` re-drives one position
through its handler; `purge` clears one with a terminal `Purged` marker.

This is different from [`protean dlq`](./dlq.md). `protean dlq` manages the
**broker** dead-letter queue (messages a broker subscription failed and moved
to `{stream_category}:dlq`). `protean eventstore dlq` covers **event-store**
subscriptions (event handlers, command handlers, projectors), which do not use
a broker DLQ; they track failed positions and, on exhaustion, leave the event
in place in the store.

All commands accept a `--domain` option for the domain module path (defaults to
the current directory). `list` and `inspect` also accept a `--json` flag for the
shared CLI result envelope; `replay` and `purge` have no JSON output.

## Commands

| Command | Description |
|---------|-------------|
| `protean eventstore dlq list` | List exhausted positions, grouped by subscription |
| `protean eventstore dlq inspect` | Re-read the failing event behind an exhausted position |
| `protean eventstore dlq replay` | Re-drive an exhausted position through its handler |
| `protean eventstore dlq purge` | Clear an exhausted position with a terminal `Purged` marker |

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

## `protean eventstore dlq replay`

Re-drives one exhausted position through its handler. It reads the failing
event and dispatches it to the handler exactly once. On success it records a
resolution, the position stops being listed as exhausted, and the command exits
`0`; on a repeat failure it reopens the position and exits `1` (the handler's
reason is in the engine logs). A subscription rebuilds its failed positions when
it starts, so a server that is already running retries a reopened position after
its next restart. The subscription read cursor is never moved, so replaying one
position does not re-process every event since the failure.

```bash
protean eventstore dlq replay 42 --domain=my_domain

# Pick one handler when a position is exhausted in more than one on the same stream
protean eventstore dlq replay 42 --handler=app.handlers.OrderHandler --domain=my_domain

# Skip the confirmation prompt (for scripts)
protean eventstore dlq replay 42 --domain=my_domain --yes
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `POSITION` | Exhausted global position (positional argument) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--subscription` | Stream category to search in | All subscriptions |
| `--handler` | Handler (its fqn or class name, as `list` prints it) when a position is exhausted in more than one | All handlers |
| `--yes`, `-y` | Skip the confirmation prompt | `False` |

Replay re-runs handler side effects, so it confirms first. Every replay can
apply its side effects again: it dispatches out-of-band and never consults the
idempotency store, and an exhausted command never recorded a success to
deduplicate against. The prompt names the target (an event handler, a projector,
or a command with or without an idempotency key) so the operator knows what is
being re-run; replaying a projector position re-applies its projection writes,
and an idempotency key helps only when the handler itself uses it to stay
idempotent.
A command whose deadline has passed is refused, because the engine would skip an
expired command; purge it instead. The deadline is checked again right before the
dispatch, so a command whose deadline ran out while the prompt was open is
refused too. A command whose handler is no longer registered is refused as well:
the dispatcher would find nothing to route it to, and the replay would report the
position resolved without running anything. A handler-level idempotency
declaration that would let replay refuse a non-idempotent target does not exist
yet.

Both `replay` and `purge` re-read the position's latest status right before they
act. If another operator's `replay` or `purge` cleared it while the prompt was
open, the command refuses and does nothing.

## `protean eventstore dlq purge`

Clears one exhausted position. The `failed-*` streams are append-only, so purge
keeps the record history and writes a new `Purged` record after the `Exhausted`
one. The position stops being listed as exhausted and a later engine restart
does not re-track it. Purge does not re-run the handler, so it needs no engine.
Like `replay`, it refuses a position that stopped being exhausted while the
prompt was open.

```bash
protean eventstore dlq purge 42 --domain=my_domain

# Skip the confirmation prompt
protean eventstore dlq purge 42 --domain=my_domain --yes
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `POSITION` | Exhausted global position (positional argument) | Required |
| `--domain` | Domain module path | `.` (current directory) |
| `--subscription` | Stream category to search in | All subscriptions |
| `--handler` | Handler (its fqn or class name, as `list` prints it) when a position is exhausted in more than one | All handlers |
| `--yes`, `-y` | Skip the confirmation prompt | `False` |

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success, including "no exhausted positions", a `replay` that resolves, and a `purge`. |
| `1` | Human mode (`--json` not set): the domain failed to load; `replay`/`purge` was not confirmed (Typer aborts, the same as every other `protean` command); or a `replay` that reopened the position (the handler failed again). |
| `2` | Usage or environment error: unknown `--subscription` or `--handler`, unknown position, an event that can no longer be re-read, an expired command, a command with no registered handler, a position another command cleared while the prompt was open, or a position exhausted in more than one subscription with no `--handler` to choose one. Under `--json`, a domain that failed to load also exits `2` and emits the error envelope. |

## Error handling

| Condition | Behavior |
|-----------|----------|
| Invalid domain path | Human mode: "Error loading Protean domain", Typer aborts with exit `1`. Under `--json`: error envelope, exit `2`. |
| `--subscription` matches no event-store subscription | "No event-store subscription found for stream category ...", exit `2` |
| `--handler` matches no event-store subscription | "No event-store subscription found for handler ...", exit `2` |
| `inspect`/`replay`/`purge` position is not exhausted | "No exhausted position ... found", exit `2` |
| `inspect`/`replay` event can no longer be read | "Could not re-read the event ...", exit `2` |
| `replay` targets a command whose deadline has passed | "Position ... targets a command whose deadline has passed ...", exit `2` |
| `replay` targets a command with no registered handler | "The command dispatcher has no handler for the message at position ...", exit `2` |
| `replay`/`purge` position is exhausted in more than one subscription | "Position ... is exhausted in multiple subscriptions ...", exit `2` |
| `replay`/`purge` position was cleared while the prompt was open | "Position ... is no longer exhausted ...", exit `2` |
| `replay`/`purge` confirmation declined | Typer aborts with exit `1` |
| `replay` handler fails again | "... position reopened. A running server retries it after its next restart.", exit `1` |

## How positions get exhausted

When an event-store handler raises, the subscription records the failed
position and retries it on each recovery pass. After `max_retries` retries it
writes an `Exhausted` record and stops retrying. The record carries the failing
event's `stream_name` and `stream_position` so `inspect` can locate the event;
records written before this was added fall back to the origin stream, read by
global position. Either read is checked against the record's global position,
which names the message store-wide. Store reads are inclusive, so if the message
a record names is gone, the read comes back with the next one in the stream, and
a restore that dropped a stream's tail can leave a later append sitting at the
per-stream ordinal the record names. `inspect` and `replay` treat either as an
event they could not re-read.

For the full error-handling guide, see
[Error Handling](../../../guides/server/error-handling.md). For subscription
lifecycle details, see
[Subscriptions](../../../concepts/async-processing/subscriptions.md).

## Domain discovery

The `protean eventstore dlq` commands use the same domain discovery mechanism
as other CLI commands. See [Domain Discovery](../project/discovery.md) for the
full resolution logic.
