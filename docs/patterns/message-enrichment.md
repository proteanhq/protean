# Enrich Messages with Cross-Cutting Metadata

## The Problem

Events and commands in a domain-driven system carry a business payload -- the
fields that matter to the domain model. But downstream processing often needs
more than the business payload. Multi-tenant applications need to know which
tenant an event belongs to. Audit systems need the user who triggered the
change. Distributed tracing requires request IDs that thread through every
message in a chain. Feature flag evaluations may need to travel with the event
so that handlers apply the same flags that were active when the event was
raised.

The naive solution is to add these fields directly to every event and command
class:

```python
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float()

    # Cross-cutting concerns polluting the domain model
    tenant_id: String(required=True)
    user_id: String()
    request_id: String()
    feature_flags: Dict()
```

This creates several problems:

- **Domain model pollution.** The `OrderPlaced` event now mixes business facts
  (`order_id`, `items`, `total`) with infrastructure concerns (`tenant_id`,
  `request_id`, `feature_flags`). The event's purpose -- recording what
  happened in the business -- is diluted by operational plumbing.

- **Repetition across every event and command.** Every event class needs the
  same cross-cutting fields. Every `raise_()` call must populate them. Every
  command must carry them. Miss one, and downstream processing silently loses
  context.

- **Coupling between domain logic and operational context.** The aggregate's
  `place_order()` method now needs to know about tenants, users, and feature
  flags. It reaches into request-scoped globals to populate fields that have
  nothing to do with order placement.

- **Schema evolution friction.** Adding a new cross-cutting field (say,
  `deployment_version`) requires updating every event class, every `raise_()`
  call, and every handler that reads the field. The change fans out across the
  entire domain.

- **Testing complexity.** Unit tests for business logic must now construct
  events with tenant IDs, user IDs, and request IDs, even when testing
  something as simple as "placing an order emits `OrderPlaced`."

The root cause: **cross-cutting metadata is being treated as domain data
instead of message infrastructure.**

---

## The Pattern

Separate cross-cutting metadata from the domain model by using **message
enrichment hooks**. Register functions that automatically inject operational
context into every event and command, storing it in `metadata.extensions`
rather than in the event's business payload.

```
Domain Model                    Enrichment Layer               Message Store
┌─────────────────┐             ┌──────────────────┐          ┌──────────────┐
│ OrderPlaced     │  raise_()   │ Event Enrichers   │          │ Event Store  │
│  order_id       │ ──────────► │  +tenant_id       │ ──────►  │  payload:    │
│  customer_id    │             │  +user_id         │          │   order_id   │
│  items          │             │  +request_id      │          │  extensions: │
│  total          │             │                   │          │   tenant_id  │
│                 │             │ (from g context)  │          │   user_id    │
└─────────────────┘             └──────────────────┘          └──────────────┘
```

The enrichment layer sits between the domain model and the message store:

1. **Enrichers are registered once** during domain initialization. They are
   plain callables -- no base class, no decorator protocol.

2. **Enrichers read from ambient context** (Protean's `g`, which is a
   thread-local/request-scoped namespace) rather than from the event payload
   or aggregate state. This keeps the domain model unaware of operational
   concerns.

3. **Enriched data lands in `metadata.extensions`**, a dict on the message's
   metadata that is persisted alongside headers, envelope, and domain meta.
   Extensions survive serialization, round-trip through the event store, and
   are available to every downstream handler.

4. **Downstream handlers access extensions via `message.metadata.extensions`**
   or `event._metadata.extensions`. They never see cross-cutting data mixed
   into the event's business fields.

The result: the domain model stays clean. Every event and command automatically
carries the operational context that infrastructure needs. Adding a new
cross-cutting concern means registering one enricher, not updating every event
class.

---

## Applying the Pattern

### Setting Up Tenant Context

In a multi-tenant SaaS application, every request arrives with a tenant
identifier -- typically extracted from an authentication token, a request
header, or a subdomain. The application stores this in Protean's global
context `g` early in the request lifecycle.

```python
# middleware.py -- FastAPI middleware that sets tenant context

from protean.utils.globals import g

class TenantContextMiddleware:
    """Extract tenant_id from the auth token and store it in g."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            # Extract tenant from auth header (simplified)
            headers = dict(scope.get("headers", []))
            token = headers.get(b"authorization", b"").decode()
            tenant_id = decode_tenant_from_token(token)
            user_id = decode_user_from_token(token)

            g.tenant_id = tenant_id
            g.user_id = user_id
            g.request_id = headers.get(
                b"x-request-id", b""
            ).decode() or str(uuid4())

        await self.app(scope, receive, send)
```

### Registering Enrichers

With tenant context available in `g`, register enrichers that inject it into
every event and command. Do this during domain setup, before `domain.init()`:

```python
# domain.py -- Domain initialization with enrichers

from protean import Domain
from protean.utils.globals import g

domain = Domain(__file__, "SaasApp")


# --- Event enrichers ---

@domain.event_enricher
def enrich_event_with_tenant(event, aggregate):
    """Inject tenant context into every domain event."""
    return {
        "tenant_id": getattr(g, "tenant_id", None),
    }


@domain.event_enricher
def enrich_event_with_audit(event, aggregate):
    """Inject user and request context for audit trails."""
    return {
        "user_id": getattr(g, "user_id", None),
        "request_id": getattr(g, "request_id", None),
    }


# --- Command enrichers ---

@domain.command_enricher
def enrich_command_with_tenant(command):
    """Inject tenant context into every command."""
    return {
        "tenant_id": getattr(g, "tenant_id", None),
    }


@domain.command_enricher
def enrich_command_with_audit(command):
    """Inject user and request context into every command."""
    return {
        "user_id": getattr(g, "user_id", None),
        "request_id": getattr(g, "request_id", None),
    }
```

### Clean Domain Model

With enrichers handling cross-cutting metadata, the domain model carries only
business data:

```python
@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    status: String(default="draft")
    items: HasMany(OrderItem)
    total: Float(default=0.0)

    def place(self) -> None:
        """Place the order and emit a domain event."""
        self._validate_can_place()
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            items=[item.to_dict() for item in self.items],
            total=self.total,
        ))


@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float()
    # No tenant_id, no user_id, no request_id.
    # Enrichers handle that.
```

When `order.place()` calls `raise_()`, Protean runs all registered event
enrichers. The resulting event has:

- **Payload:** `order_id`, `customer_id`, `items`, `total`
- **Extensions:** `tenant_id`, `user_id`, `request_id`

### Consuming Enriched Metadata

Downstream handlers access extensions from the message metadata. In async
processing, the server deserializes the stored message and enriched extensions
are available on the message object.

#### Tenant-Scoped Event Handler

```python
@domain.event_handler(part_of=Inventory)
class InventoryEventHandler(BaseEventHandler):

    @handle(OrderPlaced)
    def reserve_stock(self, event: OrderPlaced):
        # Access enriched metadata from the message in context
        tenant_id = g.message_in_context.metadata.extensions.get("tenant_id")

        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.reserve(
                order_id=event.order_id,
                quantity=item["quantity"],
                tenant_id=tenant_id,  # Pass to domain logic if needed
            )
            repo.add(inventory)
```

#### Audit-Aware Projector

```python
@domain.projector(part_of=OrderAuditProjection)
class OrderAuditProjector(BaseProjector):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        extensions = g.message_in_context.metadata.extensions

        repo = current_domain.repository_for(OrderAuditProjection)
        repo.add(OrderAuditProjection(
            order_id=event.order_id,
            action="placed",
            performed_by=extensions.get("user_id", "unknown"),
            request_id=extensions.get("request_id"),
            tenant_id=extensions.get("tenant_id"),
            timestamp=g.message_in_context.metadata.headers.time,
        ))
```

### Conditional Enrichment

Enrichers can inspect the event or aggregate to decide what metadata to add.
This is useful when different event types need different extensions:

```python
@domain.event_enricher
def enrich_with_feature_flags(event, aggregate):
    """Attach active feature flags only for events that need them."""
    # Only enrich billing-related events
    if event.__class__.__name__ in ("InvoiceGenerated", "PaymentProcessed"):
        return {
            "feature_flags": {
                "new_pricing_model": is_feature_enabled("new_pricing_model"),
                "tax_v2": is_feature_enabled("tax_v2"),
            }
        }
    return {}
```

### Combining Enrichers with Correlation IDs

Message enrichment complements Protean's built-in
[message tracing](message-tracing.md). Correlation and causation IDs live in
`metadata.domain` and are managed automatically. Extensions hold *additional*
context that the framework does not manage:

```python
@domain.event_enricher
def enrich_with_tracing(event, aggregate):
    """Bridge domain enrichment with external distributed tracing."""
    traceparent = getattr(g, "traceparent", None)
    return {
        "trace_id": traceparent.trace_id if traceparent else None,
        "span_id": traceparent.parent_id if traceparent else None,
    }
```

This lets you correlate domain events with infrastructure spans in tools like
Jaeger, Zipkin, or Datadog, while keeping the domain model free of tracing
infrastructure.

### Functional Registration

The decorator form (`@domain.event_enricher`) is convenient when enrichers are
defined alongside the domain. For enrichers defined in separate modules or
registered conditionally, use the functional form:

```python
# enrichers.py -- reusable enrichers for multiple domains

def tenant_enricher(event, aggregate):
    return {"tenant_id": getattr(g, "tenant_id", None)}


def audit_enricher(event, aggregate):
    return {
        "user_id": getattr(g, "user_id", None),
        "request_id": getattr(g, "request_id", None),
    }


def tenant_command_enricher(command):
    return {"tenant_id": getattr(g, "tenant_id", None)}
```

```python
# domain.py -- register enrichers from the module

from myapp.enrichers import (
    tenant_enricher,
    audit_enricher,
    tenant_command_enricher,
)

domain = Domain(__file__, "SaasApp")
domain.register_event_enricher(tenant_enricher)
domain.register_event_enricher(audit_enricher)
domain.register_command_enricher(tenant_command_enricher)
```

### Testing with Enrichers

Because enrichers read from `g`, tests that need enriched metadata must set up
the global context. Tests that only care about business logic can ignore
enrichers entirely -- they just get empty extensions:

```python
class TestOrderPlacement:

    def test_business_logic_without_enrichment(self, test_domain):
        """Enrichers run but produce None values -- harmless."""
        order = Order(
            customer_id="cust-1",
            total=99.99,
        )
        order.add_item(product_id="prod-1", quantity=2, price=49.99)
        order.place()

        assert order.status == "placed"
        assert len(order._events) == 1
        assert isinstance(order._events[0], OrderPlaced)

    def test_enrichment_with_tenant_context(self, test_domain):
        """Set up g to verify enrichers populate extensions."""
        g.tenant_id = "acme-corp"
        g.user_id = "user-42"
        g.request_id = "req-abc-123"

        order = Order(
            customer_id="cust-1",
            total=99.99,
        )
        order.add_item(product_id="prod-1", quantity=2, price=49.99)
        order.place()

        event = order._events[0]
        assert event._metadata.extensions["tenant_id"] == "acme-corp"
        assert event._metadata.extensions["user_id"] == "user-42"
        assert event._metadata.extensions["request_id"] == "req-abc-123"

        # Business payload is clean
        assert not hasattr(event, "tenant_id")
        assert not hasattr(event, "user_id")
```

### End-to-End: Multi-Tenant SaaS

Putting it all together, here is the flow for a multi-tenant order placement:

```
1. HTTP Request arrives
   ├── Middleware extracts tenant_id, user_id, request_id
   └── Stores them in g

2. API endpoint calls domain.process(PlaceOrder(...))
   ├── Command enrichers run → extensions: {tenant_id, user_id, request_id}
   ├── Command is stored in event store with extensions
   └── Command handler invoked

3. Handler calls order.place()
   ├── Aggregate raises OrderPlaced
   ├── Event enrichers run → extensions: {tenant_id, user_id, request_id}
   └── Event stored in aggregate._events

4. UoW commits
   ├── Events written to event store (with extensions)
   └── Outbox records created (with extensions)

5. Server picks up events
   ├── Event handler reads extensions from g.message_in_context
   ├── Projector builds tenant-scoped audit trail
   └── Extensions available for filtering, routing, and observability
```

---

## Anti-Patterns

### Adding Tenant ID to Every Event Class

```python
# Anti-pattern: cross-cutting fields in event payload

@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    tenant_id: String(required=True)   # Infrastructure concern
    user_id: String()                   # Infrastructure concern
    request_id: String()               # Infrastructure concern
    items: List(required=True)
    total: Float()
```

Every event class repeats the same fields. Every `raise_()` call must populate
them. The event schema mixes business facts with operational plumbing. When
you add a new cross-cutting field, every event class and every `raise_()` call
must change.

**Fix:** Remove cross-cutting fields from the event payload. Register enrichers
that inject them into `metadata.extensions`.

### Accessing g Directly in Domain Logic

```python
# Anti-pattern: aggregate reaching into request context

@domain.aggregate
class Order:
    def place(self) -> None:
        self.status = "placed"
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            items=[item.to_dict() for item in self.items],
            total=self.total,
            tenant_id=g.tenant_id,     # Aggregate knows about g
            user_id=g.user_id,         # Aggregate knows about request context
        ))
```

The aggregate now depends on the request context. It cannot be tested without
setting up `g`. It conflates domain behavior (placing an order) with
infrastructure plumbing (extracting tenant context).

**Fix:** Let enrichers handle `g` access. The aggregate's `raise_()` call
passes only business data. Enrichers, which are explicitly registered as
infrastructure hooks, read from `g`.

### Building One Monolithic Enricher

```python
# Anti-pattern: one enricher doing everything

@domain.event_enricher
def enrich_everything(event, aggregate):
    return {
        "tenant_id": getattr(g, "tenant_id", None),
        "user_id": getattr(g, "user_id", None),
        "request_id": getattr(g, "request_id", None),
        "ip_address": getattr(g, "ip_address", None),
        "feature_flags": get_all_feature_flags(),
        "deployment_version": os.environ.get("VERSION"),
        "region": os.environ.get("REGION"),
        "trace_id": extract_trace_id(),
        "session_id": getattr(g, "session_id", None),
    }
```

A single enricher that returns everything is harder to test, harder to
compose, and harder to disable selectively. If feature flag evaluation fails,
the entire enricher fails and the event is not appended.

**Fix:** Separate enrichers by concern. One for tenancy, one for audit, one
for feature flags, one for tracing. Each can be tested, enabled, or disabled
independently.

### Performing I/O in Enrichers

```python
# Anti-pattern: database call inside an enricher

@domain.event_enricher
def enrich_with_tenant_name(event, aggregate):
    # This runs for EVERY event raised
    tenant = TenantRepository.get(g.tenant_id)
    return {"tenant_name": tenant.name}
```

Enrichers run synchronously inside `raise_()`. A database call in an enricher
means every `raise_()` incurs a round-trip. If the database is slow or
unavailable, event raising fails.

**Fix:** Keep enrichers fast. Read only from in-memory context (`g`, environment
variables, cached values). If you need data from a database, load it once per
request in middleware and store it in `g`.

---

## Summary

| Aspect | Payload Fields | Message Enrichment |
|--------|---------------|-------------------|
| Where metadata lives | Mixed into event/command fields | Separate in `metadata.extensions` |
| Domain model impact | Polluted with infrastructure | Clean business-only fields |
| Registration | Per-event, per-command | Once per domain, applies globally |
| Adding new context | Update every event class and `raise_()` call | Register one enricher |
| Testing business logic | Must construct infrastructure fields | Enrichers produce `None`; irrelevant |
| Downstream access | `event.tenant_id` | `message.metadata.extensions["tenant_id"]` |
| Persistence | Event payload (business schema) | Extensions dict (infrastructure schema) |
| Serialization | Survives round-trips | Survives round-trips |

The principle: **event and command payloads carry business facts. Operational
context -- tenancy, audit, tracing, feature flags -- belongs in
`metadata.extensions`, injected automatically by enrichers that read from
ambient context. The domain model never knows, and never needs to know,
about the infrastructure that surrounds it.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Message Tracing](message-tracing.md) -- Correlation and causation IDs for traceability.
    - [Consuming Events from Other Domains](consuming-events-from-other-domains.md) -- Enriching external events during translation.

    **Guides:**

    - [Raising Events](../guides/domain-behavior/raising-events.md) -- How events are raised and enriched.
    - [Message Tracing](../guides/domain-behavior/message-tracing.md) -- Correlation and causation IDs.
