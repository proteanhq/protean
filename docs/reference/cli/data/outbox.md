# `protean outbox`

The `protean outbox` command group manages the transactional
[outbox](../../../guides/server/outbox.md). Today it exposes a single
command, `reconcile`, which repairs the crash window described in
[ADR-0015](../../../adr/0015-event-store-append-as-durable-anchor.md) for
event-sourced aggregates: an event that reached the event store (the durable
anchor of the commit) but whose relational outbox row never committed, leaving
the event durable yet unpublished.

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

## Commands

| Command | Description |
|---------|-------------|
| `protean outbox reconcile` | Recreate outbox rows for stored events that are missing them |

## `protean outbox reconcile`

Scans the tail of the event store for events that are durable in the store
but have no internal-broker outbox row, and creates the missing rows. It
repairs only when the newest event-sourced aggregate's event in the scan
window is missing its row, which is what a crash at the tail leaves behind.

Only events raised by this domain's event-sourced aggregates on the given
provider are repaired. For a state-based aggregate the relational row is the
state, and on a transactional provider that row commits or rolls back together
with its outbox rows. A state-based aggregate's event with no outbox row has no
saved change behind it, so it is skipped whether or not the aggregate row
exists. On a provider that keeps writes without a transaction, such as
Elasticsearch, the aggregate row can be saved while its outbox row is lost.
That change did happen, and its event stays unpublished.

Another domain's events in a shared store, commands, process manager transition
events, and events of aggregates on other providers never get outbox rows in
this provider, so they are skipped as well. A rebuilt row carries the same
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

The command reads nothing when no event-sourced aggregate is on the provider.
Otherwise the scan first checks the single newest message. When that message
is an event-sourced aggregate's event and has its row, the scan stops there.
Otherwise it reads the `--limit` window, finds the newest event-sourced
aggregate's event in it, and repairs only if that event is missing its row. In
a store shared with other domains, a run reads the full window whenever the
newest message belongs to another domain. A run also reads the full window
when the last write was a command or a state-based aggregate's event.

Reconciliation is idempotent. A run skips a row whose (`message_id`,
`target_broker`) pair is already saved, so running it repeatedly never
duplicates a row. The count that `reconcile` prints covers only the rows this
run wrote.

A run is also safe at the same time as the startup sweep or while commands are
committing. When two writers try to save the same row, whichever saves it
first keeps it and the other skips its copy, and a committing command still
commits. The exceptions depend on the provider:

- On SQLite, one transaction writes at a time. A run that waits for a
  committing command longer than the busy timeout fails with
  `database is locked`. The command still commits.
- Elasticsearch has no unique index. Two writers that save the same row at the
  same moment can both keep a row.

When a run saves a row before the command does, the row has the default
priority, not the priority of the command's request.

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
retention is not repaired. An event with no stored time is also skipped,
because its age is unknown.

## Automatic startup sweep

The same reconciliation runs once automatically when the server boots, so an
event-sourced aggregate's event whose outbox row was lost in a crash before the
relational commit gets its row back on restart without operator action:

```bash
protean server --domain=my_domain
```

The sweep is gated on the outbox being enabled, reads the store as described
above, and can never block startup. A failure during
the sweep is logged and boot continues. With `--workers N` it runs once per
worker. The sweeps can overlap with each other and with committing commands,
with the exceptions listed under the `reconcile` command above. The sweep
covers only the
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
events back from the store and re-derives the missing rows of event-sourced
aggregates' events. It skips state-based aggregates' events, for the reason
given under [`protean outbox reconcile`](#protean-outbox-reconcile). The full rationale,
including why this ordering was chosen over two-phase commit, is in
[ADR-0015: Event-Store Append as the Durable Anchor](../../../adr/0015-event-store-append-as-durable-anchor.md).

See the [Outbox Guide](../../../guides/server/outbox.md#recover-from-a-crash-reconciliation)
for the operational walkthrough.

## Domain Discovery

The `protean outbox` commands use the same domain discovery mechanism as
other CLI commands. See [Domain Discovery](../project/discovery.md) for the
full resolution logic.
