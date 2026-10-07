# Event Store Setup

<span class="pathway-tag pathway-tag-es">ES</span>

Event-sourced aggregates need somewhere to append their events and read them
back. Here is how to choose an event store, configure it, and operate it. For
the conceptual background, see
[Event Sourcing](../../concepts/architecture/event-sourcing.md).

---

## Choosing a provider

| Provider | Use case | External dependency |
|----------|----------|:-------------------:|
| `memory` | Development, testing, prototyping | None |
| `message_db` | Production, durable storage | PostgreSQL + Message DB |

Both providers implement the same interface. Your domain code is identical
regardless of provider.

---

## Configuration

### In-memory (default)

No configuration needed. This is the default when no `[event_store]`
section is present:

```toml
[event_store]
provider = "memory"
```

### Message DB (production)

Message DB runs on PostgreSQL. Install it with Docker:

```bash
docker run -d -p 5433:5432 ethangarofolo/message-db:1.2.6
```

Then configure:

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"
```

Use environment variable substitution for production:

```toml
[production.event_store]
provider = "message_db"
database_uri = "${MESSAGEDB_URL}"
```

---

## Marking aggregates as event-sourced

Only aggregates marked with `event_sourced=True` use the event store
for persistence:

```python
--8<-- "guides/change-state/event-store-setup/001.py:account"
```

Non-event-sourced aggregates continue to use the database provider
as usual. You can mix both patterns in the same domain.

---

## Reading events

### CLI

```bash
# Read events from a specific aggregate instance
protean events read "myapp::account-acc-001" --domain=myapp

# Read from a category stream (all accounts)
protean events read "myapp::account" --limit=10 --domain=myapp

# Include event payloads
protean events read "myapp::account-acc-001" --data --domain=myapp

# Domain-wide statistics
protean events stats --domain=myapp

# Search by event type
protean events search --type=Deposited --domain=myapp
```

### Programmatic

```python
--8<-- "guides/change-state/event-store-setup/001.py:read"
```

Both `read` and `read_all` return events and commands only. A read whose scope
spans snapshot streams (`$all`, or a `:snapshot-` stream) skips the snapshot
rows, so you never get a snapshot back where an event is expected.

---

## Stream naming conventions

Protean generates stream names automatically:

| Stream type | Pattern | Example |
|-------------|---------|---------|
| Instance | `{domain}::{category}-{id}` | `myapp::account-acc-001` |
| Category | `{domain}::{category}` | `myapp::account` |
| Command | `{domain}::{category}:command-{id}` | `myapp::account:command-acc-001` |
| Snapshot | `{domain}::{category}:snapshot-{id}` | `myapp::account:snapshot-acc-001` |

The category is derived from the aggregate class name (lowercased,
underscored).

---

## Temporal queries

Event-sourced aggregates support time-travel queries:

```python
--8<-- "guides/change-state/event-store-setup/001.py:datetime_import"
--8<-- "guides/change-state/event-store-setup/001.py:temporal"
```

See [Temporal Queries](./temporal-queries.md) for the full guide.

---

## Snapshots

For aggregates with many events, snapshots optimize load times by
storing periodic state checkpoints. See [Snapshots](./snapshots.md).

---

!!! tip "See also"
    - [Event Store Reference](../../reference/adapters/eventstore/index.md):
      Provider configuration details.
    - [Message DB Reference](../../reference/adapters/eventstore/message-db.md):
      Message DB-specific setup and options.
    - [Causation Tracing](../observability/correlation-and-causation.md):
      Tracing causal chains through the event store.
