# `protean outbox`

The `protean outbox` command group manages the transactional
[outbox](../../../guides/server/outbox.md). Today it exposes a single
command, `reconcile`, which repairs the crash window described in
[ADR-0015](../../../adr/0015-event-store-append-as-durable-anchor.md): an
event that reached the event store (the durable anchor of the commit) but
whose relational outbox row never committed, leaving the event durable yet
unpublished.

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

## Commands

| Command | Description |
|---------|-------------|
| `protean outbox reconcile` | Recreate outbox rows for stored events that are missing them |

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
are skipped. Cleanup deletes rows older than these retentions, and a deleted
row looks the same as one lost in a crash, so rebuilding it would send the
event again. An event lost in a crash and left unrepaired for longer than that
retention is not repaired.

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
