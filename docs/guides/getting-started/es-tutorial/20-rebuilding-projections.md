# Chapter 20: Rebuilding the World

The finance team changes their regulatory reporting requirements. The
`AccountReport` projection needs new fields and different aggregation
logic. Rather than writing a complex data migration, we simply
**rebuild the projection from scratch**: truncate the existing data,
replay all events through the updated projector, and the new projection
materializes automatically.

## How Projection Rebuilding Works

1. **Discover** the projectors for the target projection
2. **Truncate** the existing projection data
3. **Read** all events from the relevant stream categories in
   `global_position` order
4. **Dispatch** each event through the projector handlers
5. **Report** the result: events processed, events skipped, errors

## Rebuilding Programmatically

```python
with domain.domain_context():
    result = domain.rebuild_projection("AccountReport")
    print(
        f"Rebuilt '{result.projection_name}': "
        f"{result.events_dispatched} events processed, "
        f"{result.events_skipped} skipped"
    )
```

The `RebuildResult` contains:

- `projection_name` — which projection was rebuilt
- `events_dispatched` — number of events processed
- `events_skipped` — events whose type could not be resolved
- `errors` — any exceptions during processing

## Rebuilding via CLI

```shell
# Rebuild a specific projection
$ protean projection rebuild --projection=AccountReport --domain=fidelis
Rebuilt projection 'AccountReport': 245,000 events processed, 12 skipped.

# Rebuild all projections
$ protean projection rebuild --domain=fidelis
  AccountSummary: 245,000 events processed
  AccountReport: 245,000 events processed
Rebuilt 2 projection(s), 490,000 total events processed.
```

Use `--batch-size` to control memory usage for large replays:

```shell
$ protean projection rebuild --projection=AccountReport --batch-size=1000 --domain=fidelis
```

## Upcasters Apply Automatically

Events stored as v1 are automatically upcasted during replay. The
upcaster chain runs inside `to_domain_object()`, so the projector
always receives the current event version. Your projectors only need
to handle the latest schema.

## Skipped Events

Events whose type cannot be resolved (deprecated events with no
upcaster chain) are skipped with a warning, not crashed on. This
ensures a single deprecated event type does not block the entire
rebuild.

## When to Rebuild

| Scenario | Action |
|----------|--------|
| Projector logic changed | Rebuild affected projection |
| New projection added to existing system | Rebuild to backfill data |
| Projection data corrupted | Rebuild from events |
| Schema migration | Update projector + rebuild |
| After deploying upcasters | Rebuild if projectors use upcasted events |

!!! warning "Stop the server first"
    Stop `protean server` before rebuilding projections to avoid
    conflicts with concurrent event processing. After the rebuild,
    restart the server — it will resume from the current stream
    position.

## Idempotent Rebuilds

Rebuilds are idempotent. The process truncates the projection table
first, then replays from scratch. Running it twice produces the same
result. This makes rebuilds safe to retry if they fail midway.

## What We Built

- **`domain.rebuild_projection()`** for programmatic rebuilding.
- **`protean projection rebuild`** CLI for operational use.
- Automatic **upcaster integration** during replay.
- **Graceful handling** of deprecated event types.
- The confidence that projections can always be regenerated from the
  event store.

This is a fundamental advantage of Event Sourcing: the event store is
the source of truth, and all read models can be rebuilt from it at any
time.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch20.py:full"
```

## Next

[Chapter 21: The Event Store as a Database →](21-event-store-database.md)
