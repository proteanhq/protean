# Data Commands

These commands set up and migrate databases, check event-store integrity, and
let you inspect stored data.

- [`protean db`](./database.md): Database setup, teardown, and migrations
- [`protean events`](./events.md): Inspect event store contents
- [`protean eventstore`](./eventstore.md): Check event-store integrity
- [`protean eventstore dlq`](./eventstore-dlq.md): Inspect exhausted event-store positions
- [`protean snapshot`](./snapshot.md): Create aggregate snapshots
- [`protean projection`](./projection.md): Rebuild projections and report how
  far behind each one is
- [`protean outbox`](./outbox.md): Reconcile the outbox with the event store.
  Release partition keys that an abandoned row halts.
- [`protean idempotency`](./idempotency.md): Prune consume-side idempotency markers
