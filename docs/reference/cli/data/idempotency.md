# `protean idempotency`

The `protean idempotency` command group manages the **consume-side idempotency
markers** used by [`idempotent=True` projectors](../../../guides/consume-state/projectors.md#opting-into-built-in-deduplication).
Each processed event writes one `(message_id, handler)` marker
(`ProcessedMessage`); this group prunes markers that are no longer needed.

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

## Commands

| Command | Description |
|---------|-------------|
| `protean idempotency cleanup` | Prune markers older than the retention window |

## `protean idempotency cleanup`

Deletes idempotency markers older than the retention window, in bounded batches.
A marker is only useful while its event can still be redelivered, so older
markers are safe to remove. Run it periodically from a cron job; it is not
auto-scheduled today.

```bash
# Prune markers older than the configured retention window
protean idempotency cleanup --domain=my_domain

# Override the retention window and batch size for this run
protean idempotency cleanup --retention-hours=24 --batch-size=1000 --domain=my_domain
```

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--retention-hours` | Prune markers older than this many hours | `[consume_idempotency.cleanup].retention_hours` (168 = 7 days) |
| `--batch-size` | Rows deleted per bounded batch | `[consume_idempotency.cleanup].batch_size` (5000) |

**Output**

```
Deleted 1240 idempotency marker(s).
```

When no projector opts into idempotency, or nothing is old enough to prune:

```
No idempotency markers to clean up.
```

## Configuration

Defaults live under `[consume_idempotency.cleanup]` in `domain.toml`:

```toml
[consume_idempotency.cleanup]
retention_hours = 168   # Prune markers older than 7 days
batch_size = 5000       # Rows deleted per bounded batch
```

Deletes run in bounded batches of `batch_size` rows rather than one large
`DELETE`, so a backlog of millions of markers clears without holding a long lock.

## Domain Discovery

The `protean idempotency` commands use the same domain discovery mechanism as
other CLI commands. See [Domain Discovery](../project/discovery.md) for the
full resolution logic.

## See also

- [Projectors: Opting into built-in deduplication](../../../guides/consume-state/projectors.md#opting-into-built-in-deduplication) — enabling `idempotent=True`.
- [ADR-0017](../../../adr/0017-consume-side-idempotency-for-projectors.md) — the consume-side idempotency design and its boundaries.
