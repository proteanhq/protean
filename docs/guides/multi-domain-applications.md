# Multi-Domain Applications

This guide covers structuring applications with multiple bounded contexts,
each represented by a separate Protean `Domain` instance. For the conceptual
foundation, see [Bounded Contexts](../concepts/foundations/bounded-contexts.md).

---

## When to use multiple domains

Use separate domains when your application has:

- **Distinct vocabularies:** "Customer" in billing means something different
  from "Customer" in shipping
- **Independent lifecycles:** The catalog team deploys weekly; the billing
  team deploys monthly
- **Different infrastructure needs:** Orders need PostgreSQL; analytics
  needs Elasticsearch
- **Organizational boundaries:** Separate teams own separate contexts

If your entire application shares one ubiquitous language and one team
maintains it, a single domain is simpler and sufficient.

---

## Project structure

Organize each bounded context as a separate Python package with its own
domain instance, configuration, and elements:

```
my_app/
├── identity/
│   ├── __init__.py          # identity_domain = Domain(name="Identity")
│   ├── domain.toml          # Identity-specific config
│   ├── customer.py          # Customer aggregate
│   ├── events.py            # CustomerRegistered, etc.
│   └── handlers.py          # Identity command/event handlers
├── catalogue/
│   ├── __init__.py          # catalogue_domain = Domain(name="Catalogue")
│   ├── domain.toml
│   ├── product.py           # Product aggregate
│   └── handlers.py
├── fulfillment/
│   ├── __init__.py          # fulfillment_domain = Domain(name="Fulfillment")
│   ├── domain.toml
│   ├── shipment.py          # Shipment aggregate
│   ├── subscribers.py       # Consumes events from other domains
│   └── handlers.py
└── api/
    └── app.py               # FastAPI app wiring all domains together
```

Each domain's `__init__.py` creates its own `Domain` instance:

```python
# my_app/identity/__init__.py
from protean import Domain

identity_domain = Domain(name="Identity")
```

---

## Independent configuration

Each domain can have its own `domain.toml` with separate database, broker,
and event store settings:

```toml
# my_app/identity/domain.toml
[databases.default]
provider = "postgresql"
database_uri = "postgresql://localhost/identity_db"

[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"
```

```toml
# my_app/catalogue/domain.toml
[databases.default]
provider = "elasticsearch"
database_uri = "http://localhost:9200"

[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/1"
```

Alternatively, pass configuration programmatically:

```python
identity_domain = Domain(
    name="Identity",
    config={
        "databases": {
            "default": {
                "provider": "postgresql",
                "database_uri": "postgresql://localhost/identity_db",
            }
        }
    },
)
```

---

## Wiring domains in FastAPI

Use `DomainContextMiddleware` to route HTTP requests to the correct domain
context based on URL prefix:

```python
# my_app/api/app.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from protean.integrations.fastapi import (
    DomainContextMiddleware,
    register_exception_handlers,
)

from my_app.identity import identity_domain
from my_app.catalogue import catalogue_domain
from my_app.fulfillment import fulfillment_domain


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize all domains at startup
    for d in [identity_domain, catalogue_domain, fulfillment_domain]:
        d.init()
        with d.domain_context():
            d.setup_database()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/products": catalogue_domain,
        "/shipments": fulfillment_domain,
    },
)
register_exception_handlers(app)
```

Requests to `/customers/...` automatically activate `identity_domain`;
requests to `/products/...` activate `catalogue_domain`, and so on.
Requests that don't match any prefix (e.g. `/health`) pass through without
a domain context.

---

## Cross-domain communication

Domains communicate through events, never by importing each other's
aggregates or calling each other's services directly. Protean supports
two integration paths, and the right choice depends on the **strategic
relationship** between the bounded contexts.

### Choosing the right integration path

| | Co-located domains | Distributed domains |
|---|---|---|
| **Deployment** | Same repo, same process | Separate services, independent deploys |
| **Schema ownership** | You control both sides; changes are visible in one codebase | Upstream can change independently |
| **Integration mechanism** | `register_external_event()` with typed event classes | Subscribers as anti-corruption layers (raw `dict` payloads) |
| **Best for** | Process managers coordinating cross-domain workflows; event handlers syncing state across co-located contexts | Independent services, external systems, webhook ingestion |
| **DDD pattern** | Conformist / Published Language | Anti-Corruption Layer |

!!!tip
    This is not an either-or choice at the project level. A single application
    can use both paths — `register_external_event` for tightly coordinated
    domains in the same repo, and subscribers for external systems you don't
    control.

### Co-located domains: Registered external events

When multiple domains live in the same repository and share the same event
store, use `register_external_event()` to give your domain typed access to
another domain's events. This is especially useful for **process managers**
that coordinate workflows spanning multiple bounded contexts.

```python
from protean.core.event import BaseEvent
from protean.fields import Float, Identifier, String

# Define the external event class in your domain.
# This is YOUR domain's representation of the external event —
# it does not import from the other domain's package.
class PaymentReceived(BaseEvent):
    payment_id = Identifier(required=True)
    order_id = Identifier(required=True)
    amount = Float()


class StockReserved(BaseEvent):
    order_id = Identifier(required=True)
    inventory_item_id = Identifier(required=True)
    quantity = Float()


# Register external events with their type strings
fulfillment_domain.register_external_event(
    PaymentReceived, "Billing.PaymentReceived.v1"
)
fulfillment_domain.register_external_event(
    StockReserved, "Inventory.StockReserved.v1"
)
```

Now process managers and event handlers can use these typed events directly:

```python
@fulfillment_domain.process_manager(
    stream_categories=[
        "fulfillment::order",          # Own domain
        "billing::payment",            # External domain stream
        "inventory::inventory_item",   # External domain stream
    ]
)
class OrderFulfillmentPM:
    order_id = Identifier()
    status = String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentReceived, correlate="order_id")
    def on_payment_received(self, event: PaymentReceived) -> None:
        if self.status != "awaiting_payment":
            return
        self.status = "awaiting_stock"

    @handle(StockReserved, correlate="order_id")
    def on_stock_reserved(self, event: StockReserved) -> None:
        if self.status != "awaiting_stock":
            return
        self.status = "completed"
        self.mark_as_complete()
```

**Why this works for co-located domains:**

- You control both sides of the schema — changes are visible in one
  codebase and can be coordinated in a single pull request.
- Typed events give you IDE support, static analysis, and deserialization
  validation — no parsing raw dicts.
- The PM subscribes to external streams directly, keeping the coordination
  logic concise and traceable.

**Important:** The external event class is defined *in your domain*, not
imported from the other domain's package. You own the class; the type
string (`"Billing.PaymentReceived.v1"`) is the shared contract.

For syncing state across co-located contexts (without a process manager),
you can also use event handlers with `stream_category`:

```python
@fulfillment_domain.event_handler(
    part_of=Shipment,
    stream_category="identity::customer",
)
class CustomerSyncHandler:
    @handle(CustomerRegistered)
    def on_registered(self, event: CustomerRegistered):
        recipient = Recipient(
            customer_id=event.customer_id,
            name=event.name,
        )
        current_domain.repository_for(Recipient).add(recipient)
```

### Distributed domains: Subscribers as anti-corruption layers

When domains run as independent services with separate brokers — or when
you consume events from external systems you don't control — use
subscribers. Subscribers receive raw `dict` payloads and translate them
into your domain's language, acting as an anti-corruption layer:

```python
@fulfillment_domain.subscriber(stream="identity_customer_events")
class CustomerEventSubscriber:
    """Anti-corruption layer: translates external customer events."""

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type")

        if event_type == "CustomerRegistered":
            current_domain.process(
                CreateRecipient(
                    customer_id=payload["customer_id"],
                    name=payload["full_name"],  # Field name translation
                    address=payload.get("shipping_address"),
                )
            )
```

**Why this works for distributed domains:**

- **Schema isolation.** Your domain doesn't depend on the external
  domain's event classes. If the upstream renames a field, only the
  subscriber changes.
- **Translation at the boundary.** External field names, types, and
  concepts are mapped to your domain's language before entering the
  domain.
- **Independent evolution.** The upstream can deploy schema changes
  without coordinating with you. The subscriber absorbs the difference.

Key principles:

- **Subscribers receive `dict`, not typed events** -- your domain doesn't
  import the external domain's classes
- **Translate at the boundary** -- map external field names, types, and
  concepts to your domain's language
- **Everything downstream uses internal types** -- only the subscriber knows
  about the external schema

See [Consuming Events from Other Domains](../patterns/consuming-events-from-other-domains.md)
for the full pattern.

### Fact events for state transfer

When an external consumer needs complete aggregate state (not granular
deltas), enable fact events on the source aggregate:

```python
@identity_domain.aggregate(fact_events=True)
class Customer(BaseAggregate):
    name = String(required=True)
    email = String(required=True)
    segment = String()
```

Fact events publish a full snapshot with every change, making downstream
consumers simpler -- they replace their local copy wholesale instead of
applying incremental updates.

See [Fact Events as Integration Contracts](../patterns/fact-events-as-integration-contracts.md).

---

## Correlation across contexts

The same real-world entity (e.g. a customer) often appears in multiple
bounded contexts with different names and shapes. Link them using a shared
identifier:

```python
# Identity context: the authority for customer data
@identity_domain.aggregate
class Customer(BaseAggregate):
    customer_id = Auto(identifier=True)
    name = String(required=True)
    email = String(required=True)

# Fulfillment context: local representation with only relevant fields
@fulfillment_domain.aggregate
class Recipient(BaseAggregate):
    recipient_id = Auto(identifier=True)
    customer_id = Identifier(required=True)  # Correlation ID
    name = String(required=True)
    delivery_address = Text()
```

The `customer_id` in `Recipient` is a correlation ID -- it links back to
the authoritative `Customer` in the identity context without creating a
code dependency.

See [Connecting Concepts Across Bounded Contexts](../patterns/connect-concepts-across-domains.md).

---

## Running multiple domain servers

Each domain runs its own server process for async event/command processing:

```bash
# Terminal 1
protean server --domain my_app.identity

# Terminal 2
protean server --domain my_app.catalogue

# Terminal 3
protean server --domain my_app.fulfillment
```

### Monitoring across domains

The observatory supports monitoring multiple domains simultaneously:

```bash
protean observatory \
    --domain my_app.identity \
    --domain my_app.catalogue \
    --domain my_app.fulfillment
```

---

## Testing multi-domain applications

### Separate fixtures per domain

Create independent test fixtures for each domain:

```python
import pytest
from protean.integrations.pytest import DomainFixture

from my_app.identity import identity_domain
from my_app.fulfillment import fulfillment_domain


@pytest.fixture(scope="session")
def identity_fixture():
    identity_domain.config["command_processing"] = "sync"
    identity_domain.config["event_processing"] = "sync"
    fixture = DomainFixture(identity_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(scope="session")
def fulfillment_fixture():
    fulfillment_domain.config["command_processing"] = "sync"
    fulfillment_domain.config["event_processing"] = "sync"
    fixture = DomainFixture(fulfillment_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()
```

### Testing cross-domain flows

Test the boundary between domains by verifying that events from one domain
trigger the expected effects in another:

```python
def test_customer_registration_creates_recipient(
    identity_fixture, fulfillment_fixture
):
    # Act in the identity domain
    with identity_fixture.domain_context():
        identity_domain.process(
            RegisterCustomer(name="Alice", email="alice@example.com")
        )

    # Verify effect in the fulfillment domain
    with fulfillment_fixture.domain_context():
        repo = fulfillment_domain.repository_for(Recipient)
        recipients = repo.find(Q(name="Alice"))
        assert recipients.total == 1
```

### Testing FastAPI endpoints across domains

```python
from fastapi.testclient import TestClient
from my_app.api.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_customer_endpoint_uses_identity_domain(client):
    response = client.post("/customers", json={"name": "Alice"})
    assert response.status_code == 201


def test_product_endpoint_uses_catalogue_domain(client):
    response = client.get("/products")
    assert response.status_code == 200
```

---

## Design guidelines

1. **Start with one domain.** Split only when you observe genuine language
   divergence or team boundaries. Premature splitting adds complexity
   without benefit.

2. **Each domain owns its data.** Domains should not share databases. If two
   domains need the same data, one is the authority and the other holds a
   local copy synchronized through events.

3. **Communicate through events, not imports.** Never import an aggregate
   from another domain's package. Use subscribers or cross-stream event
   handlers to react to changes.

4. **Translate at boundaries.** Use the anti-corruption layer pattern
   (subscribers) to translate external concepts into your domain's language.

5. **Deploy independently when possible.** Each domain should be deployable
   on its own schedule. Shared deployment couples teams and slows everyone
   down.
