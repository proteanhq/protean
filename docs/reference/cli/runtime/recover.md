# protean recover

Recover a Protean domain after an event-store restore.

Restoring an event store from a backup can leave a subscription's checkpoint
ahead of the stream it consumes. The checkpoint stream is backed up after the
category stream, so a restore taken between the two writes names a position the
restored store no longer holds. That subscription would skip every event between
the restored head and its stale checkpoint. This command reports those
subscriptions so you can reset them before starting the engine.

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

Without `--verify-checkpoints` the command prints a hint and exits `0`;
`--verify-checkpoints` is the only supported action today.

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--verify-checkpoints` | Flag checkpoints that point past the restored stream head | `False` |
| `--domain` | Domain module path | `.` (current directory) |
| `--json` | Output raw JSON instead of a table | `False` |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All checkpoints are consistent (or no flag / no event-store subscriptions) |
| `1` | At least one checkpoint points past the restored head |
| `2` | Usage or environment error (no or unloadable domain), **under `--json`** |

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

## See also

- [protean subscriptions](subscriptions.md): lag and health for every
  subscription
- [protean eventstore verify](../data/eventstore.md): read-only integrity check
  over the event store itself
