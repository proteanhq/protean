# protean recover

Recover a Protean domain after an event-store restore.

Restoring an event store from a backup can leave a subscription's checkpoint
ahead of the stream it consumes. The checkpoint stream is backed up after the
category stream, so a restore taken between the two writes names a position the
restored store no longer holds. That subscription would skip every event between
the restored head and its stale checkpoint. `--verify-checkpoints` reports those
subscriptions so you can reset them before starting the engine, and
`--reset-beyond-head` snaps each one back to the stream head for you.

## Commands

### `protean recover --verify-checkpoints`

Report every event-store subscription whose checkpoint points past the head of
the stream it consumes.

```bash
protean recover --verify-checkpoints --domain=my_app
```

```
              Checkpoint verification: my_app
┏━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━┓
┃ Handler        ┃ Stream ┃ Checkpoint ┃ Head ┃ Verdict     ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━┩
│ OrderProjector │ order  │         10 │    5 │ beyond head │
│ PaymentHandler │ payment│          3 │    3 │ consistent  │
└────────────────┴────────┴────────────┴──────┴─────────────┘

1 of 2 checkpoint(s) point past the restored head. Reset them before starting the engine.
```

Only event-store subscriptions track checkpoints, so broker and stream
subscriptions are not examined. A fresh subscription (checkpoint `-1`, nothing
processed yet) and a caught-up one (checkpoint at or behind the head) both read
as consistent; only a checkpoint strictly ahead of the head is flagged. A
subscription whose store is unreachable, or whose position is not a number, is
reported as `unknown`: it could not be verified, so it is counted and reported
apart from the consistent ones rather than folded in as "consistent". Unknown is
not a violation (the store may be offline), so it does not change the exit code.

Without `--verify-checkpoints` the command prints a hint and exits `0`.

### `protean recover --verify-checkpoints --reset-beyond-head`

Snap each beyond-head checkpoint back to the stream head. Add
`--reset-beyond-head` to the verification run: it writes a fresh position record
to the `position-{fqn}-{category}` stream equal to the stream head, so the
subscription reads forward from just after the restored head instead of skipping
the events written after the restore.

```bash
protean recover --verify-checkpoints --reset-beyond-head --domain=my_app
```

```
              Checkpoint verification: my_app
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━┓
┃ Handler        ┃ Stream  ┃ Checkpoint ┃ Head ┃ Verdict     ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━┩
│ OrderProjector │ order   │         10 │    5 │ beyond head │
│ PaymentHandler │ payment │          3 │    3 │ consistent  │
└────────────────┴─────────┴────────────┴──────┴─────────────┘

Reset 1 beyond-head checkpoint(s) to the stream head:
  OrderProjector (order): 10 -> 5
```

The table lists every event-store subscription, then the reset line reports what
changed. The reset touches only the checkpoints found beyond the stream head. A
checkpoint at or below the head is left alone, and so is an `unknown` one that
could not be verified. It writes the stream head observed during verification, so
it only ever moves a checkpoint back and never steps a subscription forward over
events it has not processed. The run reports what it changed and exits `0`; a
later `--verify-checkpoints` run then finds those subscriptions consistent. When
the restored stream is empty the head is `-1`, and the checkpoint is reset to the
start of the stream.

If a reset write itself fails (the store is down, for example), the run resets
the reachable checkpoints, reports the ones it could not, and exits `2`. Each
successful write is durable on its own, so re-running the command picks up where
it left off.

`--reset-beyond-head` needs `--verify-checkpoints` (that pass finds what to
reset). Passing it alone is a usage error (exit `2`). Without it, no run modifies
any checkpoint.

Resetting a checkpoint changes which messages the subscription replays: moving it
back can make a subscription re-process messages. Run it against a stopped
engine, so a running subscription does not write its stale position back over the
reset.

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--verify-checkpoints` | Flag checkpoints that point past the restored stream head | `False` |
| `--reset-beyond-head` | Snap each beyond-head checkpoint back to the stream head (needs `--verify-checkpoints`) | `False` |
| `--domain` | Domain module path | `.` (current directory) |
| `--json` | Output raw JSON instead of a table | `False` |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All checkpoints are consistent (or no flag / no event-store subscriptions), or `--reset-beyond-head` snapped every beyond-head checkpoint back |
| `1` | At least one checkpoint points past the restored head (verification only, without `--reset-beyond-head`) |
| `2` | Usage or environment error: `--reset-beyond-head` without `--verify-checkpoints`, a reset write that failed, or no or unloadable domain **under `--json`** |

With `--reset-beyond-head` the run fixes each beyond-head checkpoint and exits
`0`. A verification-only run exits `1` when a checkpoint is beyond head. A reset
that could not write some checkpoints exits `2`.

A domain that cannot be loaded exits `2` under `--json` (with the error
envelope). On the default human path the same failure aborts with exit `1`.

### JSON output

Use `--json` for machine-readable output:

```bash
protean recover --verify-checkpoints --domain=my_app --json
```

The output is the shared [result envelope](../conventions.md). `status` is
`fail` (exit `1`) when any checkpoint is beyond head and `pass` (exit `0`)
otherwise. The per-subscription list is under `data.subscriptions` and the
counts are under `data.summary`. Each subscription carries a `verdict` token
(`beyond_head`, `consistent`, or `unknown`) alongside the `beyond_head` boolean,
and the summary breaks the total into `consistent`, `beyond_head`, and `unknown`
so a consumer can tell "checked and fine" from "could not read". Keys are
emitted sorted (the code uses `json.dumps(sort_keys=True)`):

```json
{
  "data": {
    "subscriptions": [
      {
        "beyond_head": true,
        "checkpoint_position": "10",
        "handler_name": "OrderProjector",
        "head_position": "5",
        "name": "order-projector",
        "stream_category": "order",
        "verdict": "beyond_head"
      }
    ],
    "summary": {
      "beyond_head": 1,
      "checked": 1,
      "consistent": 0,
      "unknown": 0
    }
  },
  "diagnostics": [],
  "status": "fail",
  "version": "0.1.0"
}
```

stdout carries exactly this one object; logs go to stderr, so a `| jq` pipe
stays parseable.

With `--reset-beyond-head` the envelope stays `pass` (exit `0`) after the reset
fixes the beyond-head checkpoints. It gains a `data.reset` list of what changed
(each entry carries the subscription `name`, `handler_name`, `stream_category`,
`previous_position`, and the `new_position` written), a `data.reset_failures`
list of any that could not be written (each with `name`, `handler_name`,
`stream_category`, and an `error`), and `summary.reset` / `summary.reset_failed`
counts. The `data.subscriptions` list and its counts still report what the
verification found, so a consumer sees both the finding and the fix. When a reset
write fails the envelope `status` is `error` and the exit code is `2`, and
`data.reset` still lists the checkpoints that were written:

```json
{
  "data": {
    "reset": [
      {
        "handler_name": "OrderProjector",
        "name": "order-projector",
        "new_position": "5",
        "previous_position": "10",
        "stream_category": "order"
      }
    ],
    "reset_failures": [],
    "subscriptions": [
      {
        "beyond_head": true,
        "checkpoint_position": "10",
        "handler_name": "OrderProjector",
        "head_position": "5",
        "name": "order-projector",
        "stream_category": "order",
        "verdict": "beyond_head"
      }
    ],
    "summary": {
      "beyond_head": 1,
      "checked": 1,
      "consistent": 0,
      "reset": 1,
      "reset_failed": 0,
      "unknown": 0
    }
  },
  "diagnostics": [],
  "status": "pass",
  "version": "0.1.0"
}
```

A plain `--verify-checkpoints --json` run (without `--reset-beyond-head`) carries
none of `data.reset`, `data.reset_failures`, `summary.reset`, or
`summary.reset_failed`.

## See also

- [protean subscriptions](subscriptions.md): lag and health for every
  subscription
- [protean eventstore verify](../data/eventstore.md): read-only integrity check
  over the event store itself
