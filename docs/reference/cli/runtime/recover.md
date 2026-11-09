# protean recover

Recover a Protean domain after an event-store restore.

Restoring an event store from a backup can leave a subscription's checkpoint
ahead of the stream it consumes. The checkpoint stream is backed up after the
category stream, so when you restore a backup taken between the two writes, the
checkpoint names a position the restored store no longer holds. A subscription
with a stale checkpoint would skip every event between the restored head and
that checkpoint. `--verify-checkpoints` reports those subscriptions so you can
reset them before starting the engine, and `--reset-beyond-head` snaps each one
back to the stream head for you.

The same restore can leave an event-store subscription's recovery pass tracking
failed positions the restored store no longer holds. The recovery pass keeps a
`recovery-checkpoint` (a watermark and an `unresolved` snapshot of positions
still awaiting retry) and a `failed-positions` stream of `Failed`/`Resolved`/
`Exhausted` records. On every restart, it rebuilds the set of positions to
retry from both. A restore can drop the message a tracked position names,
either by rolling the category stream back or by removing the specific
aggregate stream the position points at. The recovery pass then re-reads that
position, finds nothing, and retries it on every pass without ever resolving
it. `--verify-checkpoints` also reports those stale entries, and
`--reset-beyond-head` clears them.

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
as consistent; only a checkpoint strictly ahead of the head is flagged. The run
reports a subscription as `unknown` when its store is unreachable or its
position is not a number. The run could not verify that subscription, so it
counts and reports the subscription apart from the consistent ones. Unknown is
not a violation (the store may be offline), so it does not change the
exit code.

Alongside the checkpoint table, the run also reports any recovery-tracking
entries whose message a restore removed. For each event-store subscription, the
run rebuilds the set of positions the recovery pass would retry. It merges the
`recovery-checkpoint` snapshot with the `failed-positions` records after the
checkpoint watermark, the same way the subscription rebuilds the set on
restart. It then re-reads each position the way the recovery pass does: at the
record's specific stream and position when present, else at the category stream
at the global position. It names every position whose message the restored
store no longer holds:

```
1 recovery-tracking entry(ies) across 1 subscription(s) name a message the restored store no longer holds. Reset them before starting the engine.
  OrderProjector (order): 12
```

The run re-reads each position because a comparison with the stream head alone
misses one case: a restore can remove one aggregate's stream while another
aggregate has a later event. The removed position is then lower than the
category head, so the head comparison does not flag it. A stale recovery entry
fails the run the same way a beyond-head checkpoint does (exit `1`). A position
whose message is still present is left unreported. The run can verify nothing
for a subscription when the recovery streams could not be read, when a restore
left a corrupt checkpoint record, when every remaining position's re-read
failed, or when a restore left the checkpoint watermark ahead of the
failed-positions stream it reads from. The run then reports that subscription
apart as `unknown`, so it is never read as clean. Like an unknown checkpoint,
an `unknown` subscription does not change the exit code. When the run confirms
some positions stale and only a sibling could not be re-read, it still reports
the subscription as `stale` (exit `1`) and does not report `unknown`. The reset
preserves the unreadable sibling. The check is read-only: a
`--verify-checkpoints` run without `--reset-beyond-head` never writes to a
recovery-tracking stream.

Without `--verify-checkpoints` the command prints a hint and exits `0`.

### `protean recover --verify-checkpoints --reset-beyond-head`

Snap each beyond-head checkpoint back to the stream head. Add
`--reset-beyond-head` to the verification run. The run writes a fresh position
record equal to the stream head to the subscription's checkpoint stream
(`position-{subscriber_name}-{category}`). In that name, `subscriber_name` is
the handler `fqn` for event handlers, projectors and process managers, and the
dispatcher name for command handlers. The subscription then reads forward from
just after the restored head and does not skip the events written after
the restore.

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

The table lists every event-store subscription. The reset line below the table
reports what changed. The reset rewrites only the checkpoints found beyond the
stream head. A checkpoint at or below the head is left alone, and so is an
`unknown` one that could not be verified. The reset writes the stream head
observed during verification. As a result, the reset only ever moves a
checkpoint back and never moves a subscription forward past events it has not
processed. The run reports what it changed and exits `0`; a later
`--verify-checkpoints` run then finds those subscriptions consistent. When the
restored stream is empty the head is `-1`, and the checkpoint is reset to the
start of the stream.

If a reset write itself fails (the store is down, for example), the run resets
the reachable checkpoints, reports the ones it could not, and exits `2`. Each
successful write is durable on its own, so re-running the command picks up where
it left off.

`--reset-beyond-head` also clears the stale recovery-tracking entries the run
found. For each such subscription, the reset writes a fresh
`recovery-checkpoint` record. The record holds the rebuilt unresolved set with
the missing-message positions removed, and a watermark past the
`failed-positions` records the run read. The next restart then rebuilds a set
without those positions, and the recovery pass stops retrying them. The run
reports what it cleared:

```
Cleared 1 stale recovery-tracking entry(ies) whose message the restore removed:
  OrderProjector (order): 12
```

The reset drops only the entries whose message is gone. It preserves every
position whose message is still present and every position whose re-read could
not be completed. It still clears a confirmed-stale entry even when a sibling
could not be read. When a recovery reset write fails, the run names it and
exits `2`, the same as for a checkpoint reset failure. A later
`--verify-checkpoints` run then finds the subscription clean, unless a
still-unreadable position keeps it reported as `unknown`.

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
| `--verify-checkpoints` | Flag checkpoints past the restored head and recovery-tracking entries whose message the restore removed | `False` |
| `--reset-beyond-head` | Snap each beyond-head checkpoint back to the head and clear each stale recovery-tracking entry (needs `--verify-checkpoints`) | `False` |
| `--domain` | Domain module path | `.` (current directory) |
| `--json` | Output raw JSON instead of a table | `False` |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All checkpoints are consistent with no stale recovery entries (or no flag / no event-store subscriptions), or `--reset-beyond-head` cleared every beyond-head checkpoint and stale recovery entry |
| `1` | At least one checkpoint points past the restored head, or a recovery-tracking entry names a message the restored store no longer holds (verification only, without `--reset-beyond-head`) |
| `2` | Usage or environment error: `--reset-beyond-head` without `--verify-checkpoints`, a checkpoint or recovery reset write that failed, or no or unloadable domain **under `--json`** |

With `--reset-beyond-head` the run fixes each beyond-head checkpoint and stale
recovery entry and exits `0`. A verification-only run exits `1` when a checkpoint
is beyond head or a recovery-tracking entry is stale. A reset that could not
write some checkpoints or recovery entries exits `2`.

A domain that cannot be loaded exits `2` under `--json` (with the error
envelope). On the default human path the same failure aborts with exit `1`.

### JSON output

Use `--json` for machine-readable output:

```bash
protean recover --verify-checkpoints --domain=my_app --json
```

The output is the shared [result envelope](../conventions.md). `status` is
`fail` (exit `1`) when any checkpoint is beyond head or any recovery-tracking
entry is stale (see the recovery section below), and `pass` (exit `0`)
otherwise. The per-subscription list is under `data.subscriptions` and the
counts are under `data.summary`. Each subscription carries a `verdict` token
(`beyond_head`, `consistent`, or `unknown`) alongside the `beyond_head`
boolean. The summary breaks the total into `consistent`, `beyond_head`, and
`unknown`, so a consumer can tell "checked and fine" from "could not read".
Keys are emitted sorted (the code uses `json.dumps(sort_keys=True)`):

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
fixes the beyond-head checkpoints. The envelope gains a `data.reset` list of
what changed, where each entry carries the subscription `name`, `handler_name`,
`stream_category`, `previous_position`, and the `new_position` written. It also
gains a `data.reset_failures` list of the checkpoints the run could not write,
each with `name`, `handler_name`, `stream_category`, and an `error`. Last, it
gains `summary.reset` / `summary.reset_failed` counts. The `data.subscriptions`
list and its counts still report what the verification found, so a consumer
sees both the finding and the fix. When a reset write fails, the envelope
`status` is `error` and the exit code is `2`. `data.reset` still lists the
checkpoints the run wrote:

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
`data.recovery` list and `summary.recovery_stale` /
`summary.recovery_stale_positions` / `summary.recovery_unknown` counts. Each
`data.recovery` entry carries the subscription `name`, `handler_name`,
`stream_category`, `recovery_checkpoint_stream`, the `head_position` reported
as context, a `verdict` of `stale` or `unknown`, and the `stale_positions`
whose message is gone. `status` is `fail` (exit `1`) when a stale entry is
present without `--reset-beyond-head`; an `unknown` entry alone keeps `status`
`pass`. With `--reset-beyond-head` the envelope also gains a
`data.recovery_reset` list (each with `name`, `handler_name`,
`stream_category`, and the `cleared_positions` removed), a
`data.recovery_reset_failures` list of any that could not be written,
and `summary.recovery_reset` / `summary.recovery_reset_failed` counts. A run
with no recovery finding at all (neither stale nor unknown) carries none of
these keys and keeps the exact shape above. An `unknown`-only finding still
adds the `data.recovery` keys. Under `--reset-beyond-head`, an `unknown`-only
finding also adds empty `data.recovery_reset` / `data.recovery_reset_failures`
lists.

## See also

- [protean subscriptions](subscriptions.md): lag and health for every
  subscription
- [protean eventstore verify](../data/eventstore.md): read-only integrity check
  over the event store itself
