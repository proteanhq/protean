# Multi-Tenancy in Event-Driven Systems

<span class="pathway-tag pathway-cqrs">CQRS</span>
<span class="pathway-tag pathway-es">Event Sourcing</span>
<span class="pathway-tag pathway-ddd">DDD</span>

## The Problem

Multi-tenant SaaS applications serve many customers from a single deployment.
Every request, every command, every event, and every query must be scoped to a
tenant. Miss one filter and you have a data leak. Forget to propagate tenant
context through an async pipeline and a background handler operates in a vacuum
-- unable to tell which tenant's data it should touch.

In a traditional request-response application, tenant isolation is relatively
straightforward: extract the tenant from the auth token, add a WHERE clause to
every query, done. But event-driven architectures introduce a new challenge:
**the request context is gone by the time async handlers process the event.**

Consider the flow:

```
1. HTTP request arrives with tenant_id="acme"
2. Command handler creates an Order, raises OrderPlaced
3. UoW commits, event written to event store
4. Response sent, request context destroyed
   ...
5. Server picks up OrderPlaced from event store
6. Event handler runs -- but what is the tenant?
```

Between steps 4 and 5, the original request context (and its tenant identity)
no longer exists. The event handler needs to know which tenant the order belongs
to, but the event payload should not carry infrastructure concerns like tenant
IDs -- that would pollute the domain model.

The core tension: **tenant context is a cross-cutting infrastructure concern
that must survive the boundary between synchronous request handling and
asynchronous event processing, without leaking into the domain model.**

There are three classic approaches to multi-tenant data isolation:

| Strategy | How It Works | Isolation | Complexity |
|---|---|---|---|
| **Row-level** | All tenants share tables; every row has a `tenant_id` column | Lowest | Lowest |
| **Schema-per-tenant** | Each tenant gets a separate database schema (PostgreSQL) | Medium | Medium |
| **Database-per-tenant** | Each tenant gets a separate database instance | Highest | Highest |

**Row-level isolation** is the natural fit for Protean today. It works with
every adapter (memory, SQLAlchemy, Elasticsearch), requires no infrastructure
changes, and scales to thousands of tenants. The `tenant_id` is a regular field
on your aggregates, and Protean's existing primitives -- `g`, enrichers,
`metadata.extensions` -- handle context propagation end-to-end.

Schema-per-tenant and database-per-tenant are covered [later in this
document](#beyond-row-level-schema-per-tenant) as future directions.

---

## The Pattern

Row-level multi-tenancy in Protean uses four existing primitives wired together:

1. **`g` (global context)** stores the tenant ID for the duration of a request.
2. **Enrichers** automatically inject `g.tenant_id` into every event and
   command's `metadata.extensions`.
3. **The server** propagates `metadata.extensions` back into `g` when processing
   async messages -- restoring the tenant context that was lost between request
   and handler.
4. **Aggregates** carry `tenant_id` as a regular domain field for query
   filtering and data integrity.

```
Request Phase                        Async Processing Phase
┌──────────────┐                     ┌──────────────────────┐
│ Middleware    │                     │ Server Engine        │
│  g.tenant_id │                     │  reads extensions    │
│  = "acme"    │                     │  from stored event   │
└──────┬───────┘                     └──────────┬───────────┘
       │                                        │
       ▼                                        ▼
┌──────────────┐                     ┌──────────────────────┐
│ Enricher     │                     │ domain_context(      │
│  extensions: │                     │   tenant_id="acme"   │
│  tenant_id   │ ──── event ──────►  │ )                    │
│  = "acme"    │     store           │                      │
└──────────────┘                     │ g.tenant_id = "acme" │
                                     └──────────┬───────────┘
                                                │
                                                ▼
                                     ┌──────────────────────┐
                                     │ Event Handler        │
                                     │  g.tenant_id         │
                                     │  = "acme" ✓          │
                                     └──────────────────────┘
```

The result: tenant context flows transparently from the original HTTP request,
through the event store, to every async handler -- without any handler needing
to extract it manually.

---

## Applying the Pattern

### Step 1: Set Tenant Context in Middleware

Every request arrives with a tenant identifier -- from an auth token, a request
header, a subdomain, or an API key. Extract it early and store it in `g`:

```python
# middleware.py

from protean.utils.globals import g


class TenantMiddleware:
    """Extract tenant_id from the auth token and store it in g."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            token = headers.get(b"authorization", b"").decode()

            g.tenant_id = decode_tenant_from_token(token)
            g.user_id = decode_user_from_token(token)

        await self.app(scope, receive, send)
```

From this point forward, any code running in this request can access
`g.tenant_id`.

### Step 2: Register Enrichers

Enrichers automatically inject `g.tenant_id` into every event and command's
`metadata.extensions`. Register them during domain setup:

```python
# domain.py

from protean import Domain
from protean.utils.globals import g

domain = Domain(__file__, "SaasApp")


@domain.event_enricher
def enrich_event_with_tenant(event, aggregate):
    return {"tenant_id": getattr(g, "tenant_id", None)}


@domain.command_enricher
def enrich_command_with_tenant(command):
    return {"tenant_id": getattr(g, "tenant_id", None)}
```

Now every event raised by any aggregate automatically carries `tenant_id` in
its metadata -- without the aggregate knowing about tenants.

### Step 3: Model Tenant ID on Aggregates

The `tenant_id` field on aggregates is a **domain modeling decision**, not an
infrastructure hack. It's how you ensure data belongs to the right tenant:

```python
@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    tenant_id = String(required=True)
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float(default=0.0)

    def place(self):
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,
        ))
```

Notice: `place()` does not mention tenants. The enricher handles
`metadata.extensions`. The aggregate's `tenant_id` field is for storage and
query filtering -- set once when the aggregate is created, never touched by
business methods.

### Step 4: Filter Queries by Tenant

Every repository query should include the tenant filter. This is the
developer's responsibility -- Protean does not auto-inject query filters:

```python
# In a command handler or application service

repo = current_domain.repository_for(Order)

# Always filter by tenant
order = repo.find_by(id=order_id, tenant_id=g.tenant_id)

# For listing
orders = repo.find(tenant_id=g.tenant_id, status="placed")
```

!!! warning "No automatic query scoping"
    Protean does not automatically add `tenant_id` filters to queries. Every
    repository call must explicitly include the tenant filter. This is a
    conscious design choice -- automatic scoping hides behavior and makes
    debugging harder. The developer is responsible for correct filtering.

    If you want a convenience wrapper, create a base class or helper:

    ```python
    def tenant_repo(aggregate_cls):
        """Return a repository pre-filtered to the current tenant."""
        repo = current_domain.repository_for(aggregate_cls)
        return repo.find(tenant_id=g.tenant_id)
    ```

### Step 5: Access Tenant in Async Handlers

When the server processes async events, it propagates `metadata.extensions`
into `g` automatically. Handlers see the same `g.tenant_id` that was present
in the original request:

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced):
        # g.tenant_id is restored from metadata.extensions
        tenant_id = g.tenant_id

        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(
            product_id=event.product_id,
            tenant_id=tenant_id,
        )
        inventory.reserve(event.order_id, event.quantity)
        repo.add(inventory)
```

You can also access extensions directly from the message:

```python
tenant_id = g.message_in_context.metadata.extensions.get("tenant_id")
```

Both approaches work. Using `g.tenant_id` is cleaner when you only need one
value. Using `g.message_in_context.metadata.extensions` is useful when you need
to inspect the full set of enriched metadata.

---

## End-to-End Flow

Here is the complete lifecycle for a multi-tenant order placement:

```
1. HTTP Request arrives
   ├── TenantMiddleware extracts tenant_id from auth token
   └── Stores g.tenant_id = "acme"

2. API endpoint calls domain.process(PlaceOrder(...))
   ├── Command enricher runs → extensions: {"tenant_id": "acme"}
   ├── Command written to event store with extensions
   └── Command handler invoked (sync or async)

3. Command handler creates Order(tenant_id="acme", ...)
   ├── order.place() raises OrderPlaced
   ├── Event enricher runs → extensions: {"tenant_id": "acme"}
   └── Event stored in aggregate._events

4. UoW commits
   ├── Order persisted with tenant_id column
   ├── Events written to event store (with extensions in metadata)
   └── Outbox records created

5. Server picks up OrderPlaced from event store
   ├── Reads metadata.extensions: {"tenant_id": "acme"}
   ├── Creates domain_context(tenant_id="acme")
   ├── g.tenant_id is now "acme" inside handler
   └── Event handler runs with full tenant context

6. Event handler (e.g., InventoryEventHandler)
   ├── Reads g.tenant_id → "acme"
   ├── Queries repo with tenant_id filter
   └── Updates inventory for the correct tenant
```

---

## Testing

Because enrichers read from `g`, tests that need tenant context must set it up.
Tests that only care about business logic can ignore tenants -- enrichers
produce `None` values, which is harmless:

```python
class TestOrderPlacement:

    def test_business_logic_without_tenant(self, test_domain):
        """Business logic works without tenant context."""
        order = Order(
            tenant_id="test-tenant",
            customer_id="cust-1",
            total=99.99,
        )
        order.place()
        assert order.status == "placed"

    def test_enrichment_with_tenant_context(self, test_domain):
        """Enrichers populate extensions when g.tenant_id is set."""
        g.tenant_id = "acme-corp"

        order = Order(
            tenant_id="acme-corp",
            customer_id="cust-1",
            total=99.99,
        )
        order.place()

        event = order._events[0]
        assert event._metadata.extensions["tenant_id"] == "acme-corp"
        # Business payload is clean
        assert not hasattr(event, "tenant_id")
```

For testing async handlers with tenant context, construct messages with
extensions:

```python
@pytest.mark.asyncio
async def test_handler_sees_tenant_from_extensions(self, test_domain):
    """Event handler receives tenant context from metadata.extensions."""
    message = Message(
        data={...},
        metadata=Metadata(
            headers=MessageHeaders(id="msg-1", type="...", stream="..."),
            domain=DomainMeta(kind="EVENT", stream_category="order"),
            extensions={"tenant_id": "acme-corp"},
        ),
    )

    engine = Engine(domain=test_domain, test_mode=True)
    await engine.handle_message(MyEventHandler, message)

    # Verify handler saw the correct tenant
    assert captured_tenant_id == "acme-corp"
```

---

## Anti-Patterns

### Putting Tenant ID in Every Event Payload

```python
# Anti-pattern: tenant_id in the event's business fields
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    tenant_id = String(required=True)  # Infrastructure concern
    total = Float()
```

Every event class repeats `tenant_id`. Every `raise_()` call must populate it.
The event's schema mixes business facts with infrastructure plumbing.

**Fix:** Use enrichers. Tenant ID belongs in `metadata.extensions`, not in the
event payload.

### Forgetting Tenant Filters on Queries

```python
# Anti-pattern: no tenant filter → cross-tenant data leak
order = repo.get(order_id)
```

This returns the order regardless of which tenant it belongs to. In a
multi-tenant system, every query must include the tenant scope.

**Fix:** Always filter by tenant:

```python
order = repo.find_by(id=order_id, tenant_id=g.tenant_id)
```

### Accessing g.tenant_id Inside Aggregate Methods

```python
# Anti-pattern: aggregate knows about request context
@domain.aggregate
class Order:
    def place(self):
        if g.tenant_id != self.tenant_id:
            raise AuthorizationError("Wrong tenant")
        ...
```

The aggregate now depends on `g`, making it untestable without request context
and coupling domain logic to infrastructure.

**Fix:** Perform authorization checks in the handler or middleware, before
calling aggregate methods. The aggregate trusts that it was loaded correctly.

---

## Beyond Row-Level: Schema-Per-Tenant

!!! note "Future Direction"
    Schema-per-tenant requires adapter-level features that are not yet built in
    Protean. This section describes the strategy and what support would look
    like. Track progress at
    [GitHub issue #382](https://github.com/proteanhq/protean/issues/382).

In schema-per-tenant isolation, all tenants share the same PostgreSQL database
but each tenant's tables live in a separate schema. This provides stronger
isolation than row-level -- a misconfigured query cannot accidentally read
another tenant's data because the schemas are physically separate.

### How It Works

PostgreSQL schemas are namespaces within a database. By setting
`search_path` on a connection, all queries automatically target the correct
tenant's tables:

```sql
SET search_path TO tenant_acme, public;
-- Now "SELECT * FROM orders" reads from tenant_acme.orders
```

### What Protean Provides Today

The SQLAlchemy provider already supports a `schema` parameter in configuration:

```toml
[databases.default]
provider = "postgresql"
database_uri = "postgresql://localhost/saas_app"
schema = "public"  # Currently static
```

This sets the `MetaData(schema=...)` on the SQLAlchemy engine. But the schema
is fixed at provider initialization time -- it cannot change per request.

### What Would Need to Change

To support schema-per-tenant, Protean would need:

1. **A provider pool** that lazily creates and caches one provider instance per
   tenant schema. Today, providers are created once at `domain.init()` and
   bound to a single schema/engine.

2. **A tenant resolver** that maps `g.tenant_id` to a schema name (or creates
   the schema on first access for new tenants).

3. **Schema lifecycle management** -- creating schemas for new tenants,
   running migrations per schema, and cleaning up deprovisioned tenants.

### Conceptual Configuration

```toml
[databases.default]
provider = "postgresql"
database_uri = "postgresql://localhost/saas_app"

[databases.default.multitenancy]
strategy = "schema"
schema_prefix = "tenant_"  # tenant_acme, tenant_globex, etc.
```

### When to Choose Schema-Per-Tenant

- Regulated industries that require demonstrable data isolation
- Moderate tenant count (tens to low hundreds)
- Need stronger isolation than row-level but not full database separation
- PostgreSQL is the primary database

---

## Beyond Row-Level: Database-Per-Tenant

!!! note "Future Direction"
    Database-per-tenant requires adapter-level features that are not yet built
    in Protean. This section describes the strategy and what support would look
    like. Track progress at
    [GitHub issue #382](https://github.com/proteanhq/protean/issues/382).

In database-per-tenant isolation, each tenant gets their own database instance
(or at least their own logical database). This provides the strongest isolation
-- separate connections, separate credentials, separate backup schedules.

### How It Works

Each tenant maps to a different connection URI. The application must route
requests to the correct database based on the tenant:

```
tenant "acme"   → postgresql://db-acme.internal/acme_db
tenant "globex" → postgresql://db-globex.internal/globex_db
```

### What Would Need to Change

Database-per-tenant has the same fundamental gap as schema-per-tenant: Protean's
providers are created once at `domain.init()` with a fixed connection URI. To
support this strategy, Protean would need:

1. **A `MultiTenantProviderProxy`** that wraps the provider interface and
   routes `get_session()` calls to tenant-specific provider instances.

2. **Lazy provider creation** with connection pooling per tenant. Creating a
   SQLAlchemy engine per tenant is expensive -- the proxy would cache and manage
   the lifecycle of these engines.

3. **A tenant database resolver** -- a callable that maps `g.tenant_id` to a
   connection URI. This is always application-specific.

### Conceptual Configuration

```toml
[databases.default]
provider = "postgresql"
# No database_uri here -- resolved dynamically

[databases.default.multitenancy]
strategy = "database"
resolver = "myapp.tenancy.resolve_database_uri"
pool_size_per_tenant = 2
max_tenants_cached = 100
```

### When to Choose Database-Per-Tenant

- Compliance requirements mandate physical data separation
- Tenants have wildly different scale (dedicated resources per tenant)
- Per-tenant backup and restore is a requirement
- Small number of high-value tenants (enterprise B2B)

---

## Choosing a Strategy

| Dimension | Row-Level | Schema-Per-Tenant | Database-Per-Tenant |
|---|---|---|---|
| **Data isolation** | Logical (application-enforced) | Physical (schema boundary) | Physical (database boundary) |
| **Protean support** | Full (available today) | Future (adapter-level) | Future (adapter-level) |
| **Tenant count** | Thousands+ | Tens to hundreds | Tens |
| **Operational cost** | Lowest | Medium | Highest |
| **Migration complexity** | One set of migrations | Per-schema migrations | Per-database migrations |
| **Query risk** | Missing filter → data leak | Wrong schema → empty results | Wrong connection → connection error |
| **Cross-tenant queries** | Easy (same tables) | Possible (schema-qualified) | Hard (cross-database joins) |
| **Compliance** | May not satisfy strict requirements | Satisfies most regulations | Satisfies all requirements |
| **Noisy neighbor** | Shared resources | Shared database, separate tables | Fully isolated |

**Start with row-level isolation.** It works today, scales well, and covers the
vast majority of SaaS applications. Move to schema-per-tenant or
database-per-tenant only when compliance, isolation, or operational requirements
demand it.

---

## Summary

| Aspect | How Protean Handles It |
|--------|----------------------|
| Store tenant context | `g.tenant_id` via middleware |
| Propagate through events/commands | Enrichers → `metadata.extensions` |
| Restore in async handlers | Server propagates extensions back to `g` |
| Data isolation | `tenant_id` field on aggregates, explicit query filters |
| Domain model purity | Business payload clean; tenant in extensions |
| Testing | Set `g.tenant_id` in test; enrichers produce `None` without it |

The principle: **tenant identity is a cross-cutting concern that travels in
`metadata.extensions`, not in event payloads. Enrichers inject it
automatically from ambient context. The server restores it during async
processing. The domain model carries `tenant_id` as a field for data
integrity, but domain logic never reaches into `g` itself.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Message Enrichment](message-enrichment.md) -- The enricher mechanism that powers tenant context propagation.
    - [Message Tracing](message-tracing.md) -- Correlation and causation IDs for end-to-end traceability.

    **Guides:**

    - [Message Enrichment](../guides/domain-behavior/message-enrichment.md) -- Setting up enrichers step by step.
    - [Raising Events](../guides/domain-behavior/raising-events.md) -- How events are raised and enriched.
