# `protean eventstore dlq`

The `protean eventstore dlq` command group lists, inspects, replays and purges
the event store's dead-letter queue: the positions a subscription retried up to
`max_retries` and then gave up on. The subscription writes each of those
positions as an `Exhausted` record in its internal `failed-*` stream. `list`
shows the exhausted positions per subscription. `inspect` re-reads the failing
event, so you can see the event the handler could not process. `replay` sends
one position through its handler again. `purge` clears one with a terminal
`Purged` marker.

The `protean eventstore dlq` command group is separate from [`protean
dlq`](./dlq.md). `protean dlq` lists, inspects, replays and purges the
**broker** dead-letter queue (messages a broker subscription failed and moved
to `{stream_category}:dlq`). `protean eventstore dlq` covers **event-store**
subscriptions (event handlers, command handlers, projectors, process managers),
which do not use a broker DLQ. An event-store subscription tracks failed
positions and, on exhaustion, leaves the event in place in the store.

All commands accept a `--domain` option for the domain module path (defaults to
the current directory). `list` and `inspect` also accept a `--json` flag for the
shared CLI result envelope; `replay` and `purge` have no JSON output.

## Which commands does the group have?

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
                    Exhausted positions: my_domain
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
into the exhausted record), so you always see its current form. After you
replay or purge an exhausted position, the position is no longer exhausted.
`inspect` then reports it as not found.

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
resolution and exits `0`, and the position stops being listed as exhausted. On
a repeat failure it reopens the position and exits `1` (the handler's reason is
in the engine logs). A subscription rebuilds its failed positions when it
starts. A server that is already running therefore retries a reopened position
after its next restart. The subscription read cursor is never moved, so
replaying one position does not re-process every event since the failure.

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
apply its side effects again, because it dispatches out-of-band and never
consults the idempotency store. An exhausted command also never recorded a
success, so the idempotency store has nothing to deduplicate against. The
prompt names the target (an event handler, a projector, a process manager, or a
command with or without an idempotency key). The operator then knows which
target replay re-runs. Replaying a projector position re-applies its projection
writes. Replaying a process manager position can issue its commands again. An
idempotency key helps only when the handler itself uses it to stay idempotent.
Replay refuses a command past its deadline, because the engine would skip an
expired command. Purge that position instead. The `replay` command checks the
deadline again right before the dispatch. It also refuses a command that
expired while the prompt was open. `EventStoreSubscription.replay_exhausted` is
the method that dispatches. It checks the deadline once more and refuses with
the same error. The engine then checks the deadline a last time with a later
clock reading. When the deadline runs out between those two checks, the engine
still skips the command and records the position resolved. Replay also refuses
a command with no registered handler. Without that check, the dispatcher would
find no handler for the command, and the replay would report the position
resolved without running anything. Protean does not yet have a handler-level
idempotency declaration, so replay cannot refuse a non-idempotent target.

### What does `EventStoreSubscription.replay_exhausted` return?

`EventStoreSubscription.replay_exhausted` is the method `replay` calls. It
returns a `ReplayOutcome`:

| Outcome | Meaning |
|---------|---------|
| `RESOLVED` | The handler ran and succeeded. A resolution is recorded and the position stops being listed as exhausted. |
| `REOPENED` | The handler failed again. The position is reopened, and a running server retries it after its next restart. |
| `EXPIRED` | The target was a command whose deadline had passed. Nothing is dispatched and no record is written, so the position stays exhausted and can be purged. |

Both `replay` and `purge` re-read the position's latest status right before
they act. Another operator's `replay` or `purge` can clear the position while
the prompt is open. In that case the command refuses and does nothing.

## `protean eventstore dlq purge`

Clears one exhausted position. The `failed-*` streams are append-only, so purge
keeps the record history and writes a new `Purged` record after the `Exhausted`
one. The position stops being listed as exhausted. A later engine restart does
not re-track it. Purge does not re-run the handler, so it needs no engine. Like
`replay`, purge refuses a position that stopped being exhausted during the
prompt.

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

## What does each exit code mean?

| Code | Meaning |
|------|---------|
| `0` | Success, including "no exhausted positions", a `replay` that resolves, and a `purge`. |
| `1` | Human mode (`--json` not set): the domain failed to load; `replay`/`purge` was not confirmed (Typer aborts, the same as every other `protean` command); or a `replay` that reopened the position (the handler failed again). |
| `2` | Usage or environment error: unknown `--subscription` or `--handler`, unknown position, an event that can no longer be re-read, an expired command, a command with no registered handler, a position another command cleared while the prompt was open, or a position exhausted in more than one subscription with no `--handler` to choose one. Under `--json`, a domain that failed to load also exits `2` and emits the error envelope. |

## Which errors can the commands report?

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
event's `stream_name` and `stream_position`, so `inspect` can locate the event.
A record written before Protean added these two fields falls back to the origin
stream, read by global position. `inspect` and `replay` check either read
against the record's global position. The global position names the message
store-wide. Store reads are inclusive. If the message a record names is gone,
the read returns the next message in the stream. A restore can also drop a
stream's tail, and a later append can then sit at the record's per-stream
ordinal. `inspect` and `replay` treat either as an event they could not
re-read.

For the full error-handling guide, see
[Error Handling](../../../guides/server/error-handling.md). For subscription
lifecycle details, see
[Subscriptions](../../../concepts/async-processing/subscriptions.md).

## How do the commands find the domain?

The `protean eventstore dlq` commands use the same domain discovery mechanism
as other CLI commands. See [Domain Discovery](../project/discovery.md) for the
full resolution logic.
