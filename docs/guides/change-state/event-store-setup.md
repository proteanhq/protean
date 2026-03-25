# Event Store Setup

<span class="pathway-tag pathway-tag-es">ES</span>

This guide covers choosing, configuring, and operating an event store
for event-sourced aggregates. For the conceptual background, see
[Event Sourcing](../../concepts/architecture/event-sourcing.md).

---

## Choosing a provider

| Provider | Use case | External dependency |
|----------|----------|:-------------------:|
| `memory` | Development, testing, prototyping | None |
| `message_db` | Production, durable storage | PostgreSQL + Message DB |

Both providers implement the same interface -- your domain code is
identical regardless of provider.

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

Only aggregates marked with `is_event_sourced=True` use the event store
for persistence:

```python
@domain.aggregate(is_event_sourced=True)
class Account:
    balance = Float(default=0.0)

    def deposit(self, amount):
        self.raise_(Deposited(amount=amount))

    @apply(Deposited)
    def on_deposited(self, event):
        self.balance += event.amount
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
store = domain.event_store.store

# Read from beginning of stream
messages = store.read("myapp::account-acc-001")

# Read from a specific position
messages = store.read("myapp::account-acc-001", position=5)

# Read last message
last = store.read_last_message("myapp::account-acc-001")
```

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
repo = domain.repository_for(Account)

# Load at a specific version
account = repo.get(account_id, at_version=5)

# Load state as of a point in time
from datetime import datetime
account = repo.get(account_id, as_of=datetime(2024, 6, 15, 12, 0))
```

See [Temporal Queries](./temporal-queries.md) for the full guide.

---

## Snapshots

For aggregates with many events, snapshots optimize load times by
storing periodic state checkpoints. See [Snapshots](./snapshots.md).

---

!!! tip "See also"
    - [Event Store Reference](../../reference/adapters/eventstore/index.md)
      -- Provider configuration details.
    - [Message DB Reference](../../reference/adapters/eventstore/message-db.md)
      -- Message DB-specific setup and options.
    - [Causation Tracing](../observability/correlation-and-causation.md)
      -- Tracing causal chains through the event store.
