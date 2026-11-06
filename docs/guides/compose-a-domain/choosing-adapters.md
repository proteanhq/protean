# Choosing Adapters

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Protean has four infrastructure ports (**Database**, **Broker**, **Event
Store**, **Cache**) each with a pluggable adapter. Picking the right adapter
for each port is the main infrastructure decision you make when moving from
prototype to production.

This guide is decision-oriented: for each port, what's the default,
what are your options, and which one should you use for which workload.
For the TOML you paste into `domain.toml` to wire them up, see
[Configure for Production](./production-configuration.md). For the full
capability matrix of each adapter, see the
[Adapters Reference](../../reference/adapters/index.md).

## Start in memory, switch later

Protean's **memory adapters are complete implementations**, not stubs. Every
port has a memory adapter, and each one satisfies the full port contract. Your
domain code cannot tell the difference between in-memory and production
runtimes. That's deliberate. The right workflow is:

1. Build your domain against memory adapters (no Docker, no setup).
2. Write your test suite against memory adapters (fast feedback).
3. When you deploy, switch to production adapters via `domain.toml`.

No domain code changes. The only diff is the overlay in
`domain.toml`. This is also how [dual-mode testing](../../patterns/dual-mode-testing.md)
runs the same tests against both memory and real infrastructure in CI.

---

## Database

The database persists aggregate state. Every Protean application needs exactly
one `default` database. You can register additional named databases for
aggregates that you want to store in a different database (search indices,
reporting stores).

| Provider | Best for | Trade-offs |
|---|---|---|
| `memory` | Development, unit tests, prototyping | Simulated transactions (no true rollback). Data evaporates on process exit. |
| `sqlite` | Local development with real SQL semantics; single-process CLIs | No JSON/array native columns; single-writer only. Good for reproducing schema behavior without running a server. |
| `postgresql` | Production | Full relational feature set including `JSONB` and `ARRAY`. The default recommendation for most applications. |
| `elasticsearch` | Search, read-heavy analytics, document-store workloads | No transactions. Use it for read models, not aggregates whose invariants depend on atomic writes. |

**For production, use PostgreSQL** for the write side, and optionally
Elasticsearch as a named database for search-optimized projections:

```toml
[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"

[databases.search]
provider = "elasticsearch"
database_uri = { hosts = ["${ES_HOST}"] }
```

Then route specific aggregates or projections to the named database:

```python
--8<-- "guides/compose-a-domain/choosing-adapters/001.py:named-database"
```

See the [Database capability matrix](../../reference/adapters/database/index.md#which-provider-supports-which-capability)
for the exhaustive per-feature breakdown.

---

## Broker

The broker carries messages between publishers and subscribers. Typical
messages are domain events flowing through the outbox to consumers, and
external integration messages consumed by subscribers.

| Provider | Best for | Trade-offs |
|---|---|---|
| `inline` | Tests, single-process apps, synchronous processing | No durability, no consumer groups, no cross-process fan-out. Perfect for domain + application tests. |
| `redis` (Redis Streams) | Production event/command delivery | Durable, ordered per stream, consumer groups, acknowledgment + DLQ support. The default production pick. |
| `redis_pubsub` | Simple notification fan-out | List-backed queuing without consumer groups. Use when you need best-effort pub/sub without the operational complexity of streams. |

**For production, use Redis Streams** for the default broker, and
`redis_pubsub` for auxiliary notification channels if needed:

```toml
[brokers.default]
provider = "redis"
URI = "${REDIS_URL}"
```

The [outbox pattern](../server/outbox.md) is the supported way to publish
domain events to brokers. StreamSubscription reads from the outbox via the
broker, so Redis Streams (with DLQ support) is the standard choice.

!!! note "Brokers vs. event stores"
    Protean uses an **event store** (not a broker) for intra-domain event
    distribution when event sourcing is enabled. The broker is primarily for
    **integration**, publishing to partner systems, fan-out to downstream
    services, consuming external webhooks. See [Subscription
    Types](../../reference/server/subscription-types.md) for how the event
    store and the broker work together.

---

## Event Store

The event store durably records domain events in append-only streams.
It's only needed when you're using [event
sourcing](../pathways/event-sourcing.md), CQRS-only and pure DDD applications
don't require one.

| Provider | Best for | Trade-offs |
|---|---|---|
| `memory` | Development, testing, event-sourcing prototypes | In-memory only; events vanish on restart. |
| `message_db` | Production event sourcing | Requires PostgreSQL with the [Message DB](https://github.com/message-db/message-db) extension installed. Durable, ordered, replayable streams. |

**For production event sourcing, use Message DB** in a separate database on the
same server as your PostgreSQL write database:

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"
```

If you're not event-sourcing any aggregates, leave the event store on `memory`,
because no persistence is needed. Protean still uses the event store internally
for event-handler delivery in sync mode.

---

## Cache

The cache speeds up projection reads. The cache is optional, because
projections work without a cache. It is most valuable for cache-backed
projections that avoid a database round-trip entirely.

| Provider | Best for | Trade-offs |
|---|---|---|
| `memory` | Development, single-process apps | Not shared across processes; bounded by process memory. |
| `redis` | Production, distributed caches | TTL support, cross-process sharing, persistence optional. The default production pick. |

```toml
[caches.default]
provider = "redis"
URI = "${REDIS_URL}"
TTL = 300
```

In small deployments, the same Redis instance can serve the broker (on DB 0)
and the cache (on DB 2). When traffic grows, put the broker and the cache on
separate Redis instances.

---

## Start from a typical stack

A few combinations cover most real-world Protean deployments:

**For local development, keep the framework default:** all memory, no external
services. Boot time is instant, and the test suite runs in seconds. For domain
logic, everything behaves like production.

**For a small production deployment on a single server, use** PostgreSQL +
Redis + memory cache. Fits on a single VM, no orchestration needed. When
projection load demands it, add a cache adapter.

**For event-sourced production, use** PostgreSQL (aggregates) + Message DB
(event store, separate PostgreSQL database) + Redis Streams (outbox to
integration consumers) + Redis cache.

**For a search-heavy read side, use** PostgreSQL (write side) + Elasticsearch
(named `search` database for read models) + Redis Streams + Redis cache.

For the TOML that wires these together (including environment variable
substitution and overlays) see [Configure for Production: Adapter
selection](./production-configuration.md#choose-your-adapters).

---

## Switching adapters without code changes

With the port-and-adapter architecture, you choose adapters at deployment time
and change no code. When you switch from `memory` to `postgresql`, you should
change exactly one thing: the overlay in `domain.toml`.

```toml
# Base: memory for dev
[databases.default]
provider = "memory"

# Production overlay: swap in PostgreSQL
[production.databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"
```

If the switch requires code changes, you probably hit one of three problems:

- **You used an adapter-specific capability** (e.g. a raw SQL query).
  Check with `provider.has_capability(...)` and guard capability-dependent
  code, or choose adapters that share the capability you need.
- **Your tests depend on implementation details** of the memory adapter.
  Run them against a real adapter (`pytest` without
  `--protean-env=memory`) to catch this early.
- **You skipped `protean db setup`** after switching. Memory adapters
  don't need schema setup; relational ones do.

To catch drift between memory and real adapters continuously, add `pytest` in
dual-mode to your CI. See [Dual-Mode
Testing](../../patterns/dual-mode-testing.md).

---

## See also

- [Configure for Production](./production-configuration.md): TOML patterns, environment overlays, secrets.
- [Adapters Reference](../../reference/adapters/index.md): Complete capability matrices and provider-specific options.
- [Ports & Adapters](../../concepts/ports-and-adapters/index.md): Why Protean is structured this way.
- [Dual-Mode Testing](../../patterns/dual-mode-testing.md): Running the same suite against memory and real adapters.
- [Using the Outbox](../server/outbox.md): Reliable event publishing over the broker port.
- [Event Store Setup](../change-state/event-store-setup.md): Detailed event store configuration and operations.
- [Custom Adapters](../../reference/adapters/building-adapters.md): Writing your own for ports the built-in adapters don't cover.
