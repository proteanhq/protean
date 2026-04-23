# Choosing Adapters

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Protean has four infrastructure ports — **Database**, **Broker**,
**Event Store**, **Cache** — each with a pluggable adapter. Picking
the right adapter for each port is the main infrastructure decision you
make when moving from prototype to production.

This guide is decision-oriented: for each port, what's the default,
what are your options, and which one should you use for which workload.
For the TOML you paste into `domain.toml` to wire them up, see
[Configure for Production](./production-configuration.md). For the full
capability matrix of each adapter, see the
[Adapters Reference](../../reference/adapters/index.md).

## Start in memory, switch later

Protean's **memory adapters are complete implementations**, not stubs.
Every port has one, every memory adapter satisfies the full port
contract, and your domain code cannot tell the difference between
in-memory and production runtimes. That's deliberate — the right
workflow is:

1. Build your domain against memory adapters (no Docker, no setup).
2. Write your test suite against memory adapters (fast feedback).
3. Switch to production adapters via `domain.toml` when you deploy.

No domain code changes. The only diff is the overlay in
`domain.toml`. This is also how [dual-mode testing](../../patterns/dual-mode-testing.md)
runs the same tests against both memory and real infrastructure in CI.

---

## Database

The database persists aggregate state. Every Protean application needs
exactly one `default` database; you can register additional named
databases for aggregates that should live elsewhere (search indices,
reporting stores).

| Provider | Best for | Trade-offs |
|---|---|---|
| `memory` | Development, unit tests, prototyping | Simulated transactions (no true rollback). Data evaporates on process exit. |
| `sqlite` | Local development with real SQL semantics; single-process CLIs | No JSON/array native columns; single-writer only. Good for reproducing schema behavior without running a server. |
| `postgresql` | Production | Full relational feature set including `JSONB` and `ARRAY`. The default recommendation for most applications. |
| `elasticsearch` | Search, read-heavy analytics, document-store workloads | No transactions. Use it for read models, not aggregates whose invariants depend on atomic writes. |

**Typical production pick: PostgreSQL** for the write side, optionally
Elasticsearch as a named database for search-optimized projections:

```toml
[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"

[databases.search]
provider = "elasticsearch"
database_uri = "{'hosts': ['${ES_HOST}']}"
```

Then route specific aggregates or projections to the named database:

```python
@domain.projection(provider="search")
class ProductSearchIndex:
    ...
```

See the [Database capability matrix](../../reference/adapters/database/index.md#provider-capability-matrix)
for the exhaustive per-feature breakdown.

---

## Broker

The broker carries messages between publishers and subscribers —
typically domain events flowing through the outbox to consumers, or
external integration messages consumed by subscribers.

| Provider | Best for | Trade-offs |
|---|---|---|
| `inline` | Tests, single-process apps, synchronous processing | No durability, no consumer groups, no cross-process fan-out. Perfect for domain + application tests. |
| `redis` (Redis Streams) | Production event/command delivery | Durable, ordered per stream, consumer groups, acknowledgment + DLQ support. The default production pick. |
| `redis_pubsub` | Simple notification fan-out | List-backed queuing without consumer groups. Use when you need best-effort pub/sub without the operational complexity of streams. |

**Typical production pick: Redis Streams** for the default broker, and
`redis_pubsub` for auxiliary notification channels if needed:

```toml
[brokers.default]
provider = "redis"
URI = "${REDIS_URL}"
```

The [outbox pattern](../server/outbox.md) is the supported way to
publish domain events to brokers — StreamSubscription reads from the
outbox via the broker, which is why Redis Streams (with DLQ support)
is the standard choice.

!!! note "Brokers vs. event stores"
    Protean uses an **event store** (not a broker) for intra-domain
    event distribution when event sourcing is enabled. The broker is
    primarily for **integration** — publishing to partner systems,
    fan-out to downstream services, consuming external webhooks. See
    [Subscription Types](../../reference/server/subscription-types.md)
    for how the two fit together.

---

## Event Store

The event store durably records domain events in append-only streams.
It's only needed when you're using [event sourcing](../pathways/event-sourcing.md) —
CQRS-only and pure DDD applications don't require one.

| Provider | Best for | Trade-offs |
|---|---|---|
| `memory` | Development, testing, event-sourcing prototypes | In-memory only; events vanish on restart. |
| `message_db` | Production event sourcing | Requires PostgreSQL with the [Message DB](https://github.com/message-db/message-db) extension installed. Durable, ordered, replayable streams. |

**Typical production pick: Message DB** co-located with your
PostgreSQL write database, in a separate database on the same server:

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"
```

If you're not event-sourcing any aggregates, leave the event store on
`memory` — Protean still uses it internally for event-handler delivery
in sync mode, but no persistence is needed.

---

## Cache

The cache speeds up projection reads. It's optional — projections work
fine without a cache — and is most valuable for cache-backed
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

The same Redis instance can host the broker (on DB 0) and cache (on DB
2) in small deployments; isolate them when traffic grows.

---

## Typical stacks

A few combinations cover most real-world Protean deployments:

**Local development (framework default):** all memory, no external
services. Boot time is instant, the test suite runs in seconds, and
everything behaves like production for domain logic.

**Small production (single server):** PostgreSQL + Redis + memory
cache. Fits on a single VM, no orchestration needed. Add a cache
adapter later when projection load demands it.

**Event-sourced production:** PostgreSQL (aggregates) + Message DB
(event store, separate PostgreSQL database) + Redis Streams (outbox to
integration consumers) + Redis cache.

**Search-heavy read side:** PostgreSQL (write side) + Elasticsearch
(named `search` database for read models) + Redis Streams +
Redis cache.

For the TOML that wires these together — including environment variable
substitution and overlays — see
[Configure for Production: Adapter selection](./production-configuration.md#adapter-selection).

---

## Switching adapters without code changes

The whole point of the port-and-adapter architecture is that adapter
choice is a deployment decision, not a code decision. When you switch
from `memory` to `postgresql`, you should change exactly one thing: the
overlay in `domain.toml`.

```toml
# Base: memory for dev
[databases.default]
provider = "memory"

# Production overlay: swap in PostgreSQL
[production.databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"
```

If the switch requires code changes, one of three things is probably
happening:

- **You used an adapter-specific capability** (e.g. a raw SQL query).
  Check with `provider.has_capability(...)` and guard capability-dependent
  code, or choose adapters that share the capability you need.
- **Your tests depend on implementation details** of the memory adapter.
  Run them against a real adapter (`pytest` without
  `--protean-env=memory`) to catch this early.
- **You skipped `protean db setup`** after switching. Memory adapters
  don't need schema setup; relational ones do.

Add `pytest` in dual-mode to your CI to catch this drift continuously —
see [Dual-Mode Testing](../../patterns/dual-mode-testing.md).

---

## See also

- [Configure for Production](./production-configuration.md) — TOML patterns, environment overlays, secrets.
- [Adapters Reference](../../reference/adapters/index.md) — Complete capability matrices and provider-specific options.
- [Ports & Adapters](../../concepts/ports-and-adapters/index.md) — Why Protean is structured this way.
- [Dual-Mode Testing](../../patterns/dual-mode-testing.md) — Running the same suite against memory and real adapters.
- [Using the Outbox](../server/outbox.md) — Reliable event publishing over the broker port.
- [Event Store Setup](../change-state/event-store-setup.md) — Detailed event store configuration and operations.
- [Custom Adapters](../../community/contributing/adapters.md) — Writing your own for ports the built-in adapters don't cover.
