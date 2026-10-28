# `protean outbox`

The `protean outbox` command group manages the transactional
[outbox](../../../guides/server/outbox.md). `reconcile` repairs the crash
window described in
[ADR-0015](../../../adr/0015-event-store-append-as-durable-anchor.md): an
event that reached the event store (the durable anchor of the commit) but
whose relational outbox row never committed, leaving the event durable yet
unpublished. `halted`, `retry` and `discard` find and release a partition key
that an abandoned row has halted.

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

## Commands

| Command | Description |
|---------|-------------|
| `protean outbox reconcile` | Recreate outbox rows for stored events that are missing them |
| `protean outbox halted` | List the partition keys that an abandoned row halts |
| `protean outbox retry` | Send a failed or abandoned row back to `pending` |
| `protean outbox discard` | Skip a failed or abandoned row for good, keeping it for audit |

## `protean outbox reconcile`

Scans the tail of the event store for events that are durable in the store
but have no internal-broker outbox row, and creates the missing rows. It
repairs only when the newest of this domain's events in the scan window is
missing its row, which is what a crash at the tail leaves behind. Only events
raised by this domain's aggregates on the given provider are repaired. Another
domain's events in a shared store, commands, process manager transition
events, and events of aggregates on other providers never get outbox rows in
this provider, so they are skipped. A rebuilt row carries the same
`partition_key` the original commit would have set. This is
the manual counterpart to the [automatic startup
sweep](#automatic-startup-sweep), run it on demand after a suspected crash, or
from a cron job as a periodic safety net.

```bash
# Reconcile the default provider's outbox
protean outbox reconcile --domain=my_domain

# Reconcile a named provider, scanning a wider window
protean outbox reconcile --provider=analytics --limit=5000 --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--provider` | Provider whose outbox to reconcile | `default` |
| `--limit` | Most recent event-store messages to scan for gaps, skipped messages included | `1000` |

**Output**

```
Reconciled 2 outbox row(s) from the event store.
```

When the outbox already matches the event store (the common, no-crash case)
nothing is rewritten:

```
Nothing to reconcile: no event in the scanned window is missing its outbox row.
```

The scan first checks the single newest message. When that message is one of
this domain's events and has its row, the scan stops there. Otherwise it reads
the `--limit` window, finds the newest of this domain's events in it, and
repairs only if that event is missing its row. In a store shared with other
domains, or when the last write was a command, every run reads the full
window. Reconciliation
is idempotent, the composite unique index on (`message_id`, `target_broker`) means running it
repeatedly, or concurrently with the startup sweep, never duplicates a row.

A `published` event also gets back one row per broker in
`[outbox].external_brokers`, with the same `partition_key` as its internal row.
Reconciliation reads the event's current `published` flag and the current
`external_brokers` list, because neither is stored with the event. An event
counts as missing only when its internal-broker row is missing, since all of an
event's rows are saved in one commit. So a broker added to `external_brokers`
later is not back-filled for events that still have their internal row. The
count in the output includes the external rows.

Events older than the shorter of `[outbox.cleanup].published_retention_hours`
(default 168) and `[outbox.cleanup].abandoned_retention_hours` (default 720)
are skipped. Cleanup deletes rows older than these retentions (it keeps
abandoned rows that have a partition key), and a deleted row looks the same as
one lost in a crash, so rebuilding it would send the event again. An event lost in a crash and left unrepaired for longer than that
retention is not repaired. An event with no stored time is also skipped,
because its age is unknown.

A row the reconciler abandons records `last_processed_at`, so
`cleanup_old_abandoned()` removes it once `abandoned_retention_hours` has
passed. A row abandoned because its partition key is invalid carries
`last_error["reason"]` of "Invalid partition key".

## `protean outbox halted`

Lists the partition keys whose earliest row that still holds the key is
`abandoned`. Rows that are `pending`, `processing`, `failed` or `abandoned`
hold the key. `published` and `discarded` rows do not, so they are skipped. A
partition key is the value set by a handler's
[`sequential_by`](../../server/sequential-by.md), and the processor publishes a
key's rows in commit order. Rows are grouped by target broker, stream
category, partition key and [priority lane](../../../guides/server/using-priority-lanes.md),
the same groups the processor uses, so a key is listed exactly when the
processor holds its later rows behind an abandoned row. A key whose earliest
holding row is `pending`, `processing` or `failed` also has its later rows
held, but it is not listed, because the processor will still publish or retry
that row.

```bash
protean outbox halted --domain=my_domain
protean outbox halted --json --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--provider` | Provider whose outbox to inspect | `default` |
| `--json` | Print the [result envelope](../conventions.md#the-result-envelope) as JSON | off |

**Output**

```
1 halted group(s) of broker, stream category, partition key and lane:
- default shop::order key=cust-42 lane=primary: head row 6f1c2a9e-... is abandoned (broker rejected the payload), 3 row(s) waiting
```

Each line names the target broker, the stream category, the partition key and
the lane, then the abandoned row at the head of the key, the message from its
`last_error`, and how many later rows of the key are waiting. There is one
line per group, so a key with rows for two brokers or in both lanes appears
once for each. With no halted key it prints `No partition key is halted.` and
exits 0. The scan reads the abandoned rows a page at a time, so a row whose
status changes while it runs can be missed or listed twice.

Under `--json`, `data.halted` holds one object per halted group. The
`last_error` below is shortened. A real one also holds the `traceback`,
`failed_at` and `retry_count` of the last failure, and prints across several
lines:

```json
{
  "data": {
    "halted": [
      {
        "head_id": "6f1c2a9e-...",
        "lane": "primary",
        "last_error": {
          "message": "broker rejected the payload",
          "reason": "Max retries exceeded"
        },
        "partition_key": "cust-42",
        "status": "abandoned",
        "stream_category": "shop::order",
        "target_broker": "default",
        "waiting": 3
      }
    ]
  },
  "diagnostics": [],
  "status": "pass",
  "version": "0.1.0"
}
```

`lane` is `primary` or `backfill`. `last_error` is the row's stored error, or
`null` when it has none.

## `protean outbox retry`

Sends a `failed` or `abandoned` row back to `pending` with its retry count at
zero and no retry delay, so it gets the full number of attempts again. A row
whose `max_retries` is 0 gets one attempt. The processor can then claim the
row, in the same priority and commit order as any other row, and still only
after the earlier rows of its key. The later rows of its key publish after
it.

```bash
protean outbox retry 6f1c2a9e-... --domain=my_domain
```

**Arguments and options**

| Argument / Option | Description | Default |
|-------------------|-------------|---------|
| `ROW_ID` | Id of the outbox row, as shown by `halted` | required |
| `--domain` | Domain module path | `.` (current directory) |
| `--provider` | Provider whose outbox holds the row | `default` |

**Output**

```
Outbox row 6f1c2a9e-... is pending and will be published again.
```

## `protean outbox discard`

Skips a `failed` or `abandoned` row for good. The row is never published, so
its event is dropped for that broker, and the later rows of its key publish
without it. The row stays in the outbox with the `discarded` status. Its
`last_error` keeps the original error and gains `discarded_at` and
`discard_reason`. Cleanup deletes it `abandoned_retention_hours` after it was
discarded. The reason cannot be empty.

```bash
protean outbox discard 6f1c2a9e-... --reason "payload rejected by the broker" --domain=my_domain
```

**Arguments and options**

| Argument / Option | Description | Default |
|-------------------|-------------|---------|
| `ROW_ID` | Id of the outbox row, as shown by `halted` | required |
| `--reason` | Why the row is skipped, stored on the row | required |
| `--domain` | Domain module path | `.` (current directory) |
| `--provider` | Provider whose outbox holds the row | `default` |

**Output**

```
Outbox row 6f1c2a9e-... is discarded and will not be published.
```

## Automatic startup sweep

The same reconciliation runs once automatically when the server boots, so a
crash before the relational commit self-heals on restart without operator
action:

```bash
protean server --domain=my_domain
```

The sweep is gated on the outbox being enabled, reads the store as described
above, and can never block startup. A failure during
the sweep is logged and boot continues. With `--workers N` it runs once per
worker; the idempotent index makes the overlap safe. The sweep covers only the
`default` provider. Run `protean outbox reconcile --provider=<name>` for
aggregates on other providers.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Invalid domain path | Aborts with "Error loading Protean domain" |
| Outbox not enabled for the domain | Aborts with "Outbox is not enabled for this domain", naming `default_subscription_type = "stream"` and the older `enable_outbox` switch, which also needs it |
| Nothing to reconcile | Prints "Nothing to reconcile: no event in the scanned window is missing its outbox row" |
| `halted --json` with an invalid domain path or the outbox not enabled | Prints the error envelope (`status` `error`, the message under `data.error`) and exits 2 |
| `halted` finds no halted key | Prints "No partition key is halted." and exits 0 |
| `retry` or `discard` with an unknown id | Aborts with "No outbox row with id ..." and changes nothing |
| `retry` or `discard` on a row that is not `failed` or `abandoned` | Aborts with "Outbox row ... is \<status\>. Only a failed or abandoned row can be retried or discarded." and changes nothing |
| `retry` or `discard` on a row a worker claims or fails while the command runs | Aborts with "Outbox row ... changed while the command ran" and changes nothing |
| `discard` without `--reason`, or with an empty one | Usage error, exit code 2 |
| `halted`, `retry` or `discard` with a `--provider` that has no outbox | Prints "No outbox for provider ..." (the error envelope under `halted --json`) and exits 2 |

## How reconciliation works

The commit sequence appends events to the event store *before* committing the
relational transaction that carries aggregate state and the outbox rows, so the
event store is the durable anchor. A crash in the window between the two leaves
events stored but their outbox rows uncommitted. Reconciliation reads those
events back from the store and re-derives the missing rows. The full rationale,
including why this ordering was chosen over two-phase commit, is in
[ADR-0015: Event-Store Append as the Durable Anchor](../../../adr/0015-event-store-append-as-durable-anchor.md).

See the [Outbox Guide](../../../guides/server/outbox.md#recover-from-a-crash-reconciliation)
for the operational walkthrough.

## Domain Discovery

The `protean outbox` commands use the same domain discovery mechanism as
other CLI commands. See [Domain Discovery](../project/discovery.md) for the
full resolution logic.
