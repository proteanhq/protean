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

Scans the tail of the event store and creates an outbox row for any event
that is durable in the store but has no internal-broker outbox row. This is
the manual counterpart to the [automatic startup
sweep](#automatic-startup-sweep) — run it on demand after a suspected crash,
or from a cron job as a periodic safety net.

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
| `--limit` | Most recent events to scan for gaps | `1000` |

**Output**

```
Reconciled 2 outbox row(s) from the event store.
```

When the outbox already matches the event store — the common, no-crash case
— nothing is rewritten:

```
Nothing to reconcile: the outbox is consistent with the event store.
```

The scan is cheap when there is nothing to repair: it first checks the single
newest event, and only walks the `--limit` window when that newest event is
itself missing its row (the signature of a crash at the tail). Reconciliation
is idempotent — the composite unique index on (`message_id`, `target_broker`)
means running it repeatedly, or concurrently with the startup sweep, never
duplicates a row.

Only the **internal-broker** row is reconciled. External published-broker rows
(from `[outbox].external_brokers`) are re-derived by the outbox processor once
the internal row is published, and are out of scope for this command.

## Automatic startup sweep

The same reconciliation runs once automatically when the server boots, so a
crash before the relational commit self-heals on restart without operator
action:

```bash
protean server --domain=my_domain
```

The sweep is gated on the outbox being enabled, is cheap in the common case
(the newest-event check above), and can never block startup — a failure during
the sweep is logged and boot continues. With `--workers N` it runs once per
worker; the idempotent index makes the overlap safe.

## Error Handling

| Condition | Behavior |
|-----------|----------|
| Invalid domain path | Aborts with "Error loading Protean domain" |
| Outbox not enabled for the domain | Aborts with "Outbox is not enabled for this domain" |
| Nothing to reconcile | Prints "Nothing to reconcile: the outbox is consistent with the event store" |

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
