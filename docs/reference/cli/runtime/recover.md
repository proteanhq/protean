# protean recover

Recover a Protean domain after an event-store restore.

Restoring an event store from a backup can leave a subscription's checkpoint
ahead of the stream it consumes. The checkpoint stream is backed up after the
category stream, so a restore taken between the two writes names a position the
restored store no longer holds. That subscription would skip every event between
the restored head and its stale checkpoint. `--verify-checkpoints` reports those
subscriptions so you can reset them before starting the engine, and
`--reset-beyond-head` snaps each one back to the stream head for you.

The same restore can leave an event-store subscription's recovery pass tracking
failed positions the restored store no longer holds. The recovery pass keeps a
`recovery-checkpoint` (a watermark and an `unresolved` snapshot of positions
still awaiting retry) and a `failed-positions` stream of `Failed`/`Resolved`/
`Exhausted` records, and rebuilds the set of positions to retry from them on
every restart. When a restore drops the message a tracked position names (it
rolled the category stream back, or removed the specific aggregate stream the
position points at), the recovery pass re-reads it, finds nothing, and retries it
on every pass without ever resolving it. `--verify-checkpoints` also reports those
stale entries, and `--reset-beyond-head` clears them.

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

Alongside the checkpoint table, the run also reports any recovery-tracking
entries whose message a restore removed. For each event-store subscription it
rebuilds the set of positions the recovery pass would retry (the
`recovery-checkpoint` snapshot merged with the `failed-positions` records after
the checkpoint watermark, the same way the subscription rebuilds it on restart),
then re-reads each the way the recovery pass does (the record's specific stream
and position when present, else the category stream at the global position) and
names every one whose message the restored store no longer holds:

```
1 recovery-tracking entry(ies) across 1 subscription(s) name a message the restored store no longer holds. Reset them before starting the engine.
  OrderProjector (order): 12
```

Re-reading each position, rather than only comparing it to the stream head,
catches a restore that removed one aggregate's stream while another aggregate has
a later event: the removed position then sits below the category head, so a head
comparison alone would miss it. A stale recovery entry fails the run the same way
a beyond-head checkpoint does (exit `1`). A position whose message is still
present is left unreported. A subscription whose recovery streams could not be
read (the store failed, or a restore left a corrupt checkpoint record) is
reported apart as unverified so it is never read as clean; like an unknown
checkpoint, that does not change the exit code. The check is read-only: a
`--verify-checkpoints` run never writes to a recovery-tracking stream.

Without `--verify-checkpoints` the command prints a hint and exits `0`.

### `protean recover --verify-checkpoints --reset-beyond-head`

Snap each beyond-head checkpoint back to the stream head. Add
`--reset-beyond-head` to the verification run: it writes a fresh position record
to the subscription's checkpoint stream (`position-{subscriber_name}-{category}`,
where `subscriber_name` is the handler `fqn` for event handlers, projectors and
process managers, and the dispatcher name for command handlers) equal to the
stream head, so the subscription reads forward from just after the restored head
instead of skipping the events written after the restore.

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

`--reset-beyond-head` also clears the stale recovery-tracking entries the run
found. For each such subscription it writes a fresh `recovery-checkpoint` record
holding the rebuilt unresolved set with the beyond-head positions removed and a
watermark past the `failed-positions` records it read, so the next restart
rebuilds a set without them and the recovery pass stops chasing them. It reports
what it cleared:

```
Cleared 1 stale recovery-tracking entry(ies) whose message the restore removed:
  OrderProjector (order): 12
```

Only the entries whose message is gone are dropped; every position whose message
is still present is preserved. A recovery reset write that fails is named and the
run exits `2`, the same as a checkpoint reset failure. A later
`--verify-checkpoints` run then finds the subscription clean.

`--reset-beyond-head` needs `--verify-checkpoints` (that pass finds what to
reset). Passing it alone is a usage error (exit `2`). Without it, no run modifies
any checkpoint or recovery-tracking stream.

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
| `0` | All checkpoints are consistent with no stale recovery entries (or no flag / no event-store subscriptions), or `--reset-beyond-head` cleared every beyond-head checkpoint and recovery entry |
| `1` | At least one checkpoint or recovery-tracking entry points past the restored head (verification only, without `--reset-beyond-head`) |
| `2` | Usage or environment error: `--reset-beyond-head` without `--verify-checkpoints`, a checkpoint or recovery reset write that failed, or no or unloadable domain **under `--json`** |

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

When the run finds a recovery-tracking entry, the envelope gains a
`data.recovery` list (each entry carries the subscription `name`,
`handler_name`, `stream_category`, `recovery_checkpoint_stream`, the
`head_position` reported as context, a `verdict` of `stale` or `unknown`, and the
`stale_positions` whose message is gone) and `summary.recovery_stale` /
`summary.recovery_stale_positions` / `summary.recovery_unknown` counts. `status`
is `fail` (exit `1`) when a stale entry is present without `--reset-beyond-head`;
an `unknown` entry alone keeps `status` `pass`.
With `--reset-beyond-head` the envelope also gains a `data.recovery_reset` list
(each with `name`, `handler_name`, `stream_category`, and the `cleared_positions`
removed), a `data.recovery_reset_failures` list of any that could not be written,
and `summary.recovery_reset` / `summary.recovery_reset_failed` counts. A run with
no stale recovery entry carries none of these keys and keeps the exact shape
above.

## See also

- [protean subscriptions](subscriptions.md): lag and health for every
  subscription
- [protean eventstore verify](../data/eventstore.md): read-only integrity check
  over the event store itself
