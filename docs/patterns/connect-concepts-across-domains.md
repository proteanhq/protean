# Connecting Concepts Across Bounded Contexts

## The Problem

In a non-trivial system, the same real-world concept inevitably appears in
multiple bounded contexts. A "Customer" exists in Sales, Billing, Shipping, and
Support -- but each context cares about different attributes, enforces different
rules, and evolves at its own pace.

This creates a tension:

- **The contexts need to know about each other's state.** When Sales registers a
  new customer, Billing needs to create an account. When Billing suspends an
  account, Support needs to know. When Shipping updates an address, Sales may want
  to reflect it.
- **The contexts must not be coupled.** If Billing directly queries the Sales
  database for customer information, it becomes dependent on Sales' schema,
  availability, and deployment schedule. Changes in Sales break Billing. The
  bounded contexts lose their independence.

The naive solutions all have problems:

- **Shared database**: All contexts read from the same customer table. Schema
  changes require coordinated deployments. One context's performance issues affect
  all others. The "bounded" in bounded context becomes meaningless.
- **Direct API calls**: Billing calls Sales' API to get customer data. Billing is
  now coupled to Sales' availability. If Sales is down, Billing cannot function.
  Latency compounds across call chains.
- **Shared domain model**: All contexts import the same `Customer` class.
  Requirements diverge, and the shared class accumulates attributes from every
  context until it becomes an unmanageable God Object.

Domain-Driven Design solves this through a combination of **separate models per
context**, **identity correlation**, and **event-driven state propagation**.

---

## Two Variations

Before diving into solutions, it's important to distinguish two scenarios that
look similar but require different approaches:

### Different Concepts, Same Name

"Account" in Banking means a financial account with a balance and transaction
history. "Account" in Identity Management means a user account with credentials
and permissions. These share a name but are fundamentally different concepts.

The solution here is simple: **rename to remove ambiguity**. Use the Ubiquitous
Language of each context. `FinancialAccount` in Banking, `UserAccount` in
Identity Management. No connection is needed because these are not the same thing.

### Same Concept, Multiple Contexts

A "Customer" who places orders in Sales is the same person who receives invoices
in Billing and packages in Shipping. The real-world entity is one, but each
bounded context models a different facet of it:

- **Sales** cares about preferences, order history, and segmentation.
- **Billing** cares about payment methods, invoices, and account standing.
- **Shipping** cares about addresses, delivery preferences, and logistics.

These are different *models* of the same *real-world entity*. They need to stay
connected. This pattern addresses this second variation.

---

## The Pattern: Identity Correlation and Event Propagation

The solution has three parts:

1. **Shared identity**: All contexts refer to the same real-world entity using a
   common identifier (the correlation ID).
2. **Event propagation**: The context that "owns" the concept publishes lifecycle
   events. Other contexts subscribe to these events and build their own local
   representations.
3. **Local models**: Each context maintains its own model of the concept, shaped
   by its specific needs.

```
┌──────────────┐         CustomerRegistered          ┌──────────────┐
│              │    ─ ─ ─{ customer_id: "c-123" }─ ─ ─>              │
│    Sales     │         name: "Jane Doe"            │   Billing    │
│   Context    │         email: "jane@..."           │   Context    │
│              │                                      │              │
│  Customer    │         CustomerAddressUpdated       │  Account     │
│  aggregate   │    ─ ─ ─{ customer_id: "c-123" }─ ─ ─>              │
│              │                                      │  customer_id │
└──────────────┘                                      │  (correlated)│
       │                                              └──────────────┘
       │              CustomerRegistered
       │         ─ ─ ─{ customer_id: "c-123" }─ ─ ─ ┐
       │              name: "Jane Doe"               │
       ▼              address: "..."                 ▼
┌──────────────┐                              ┌──────────────┐
│              │                              │              │
│  Shipping    │                              │   Support    │
│  Context     │                              │   Context    │
│              │                              │              │
│  Recipient   │                              │  Contact     │
│  aggregate   │                              │  aggregate   │
│              │                              │              │
│  customer_id │                              │  customer_id │
│  (correlated)│                              │  (correlated)│
└──────────────┘                              └──────────────┘
```

The key insight: **the customer_id is the thread that connects all
representations**. Each context stores this identifier and uses it to correlate
incoming events with its local model.

---

## Step 1: Establish the Source of Truth

One bounded context is the **authority** for a concept's lifecycle. This is the
context where the concept is created, where its core identity is established, and
where fundamental lifecycle changes (registration, suspension, deletion)
originate.

For "Customer", this is typically the Sales or Identity context:

```python
# Sales context -- the authority for Customer
from protean import Domain
from protean.fields import Auto, String, Identifier

sales = Domain(__file__, "Sales")


@sales.aggregate
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True, max_length=100)
    email: String(required=True)
    segment: String(choices=CustomerSegment, default="STANDARD")
```

This aggregate owns the `customer_id`. When a customer is registered, this
context generates the identity (following the
[Creating Identities Early](creating-identities-early.md) pattern) and publishes
the fact through events.

---

## Step 2: Publish Lifecycle Events

The authoritative context raises events for every significant lifecycle change.
These events carry the **shared identity** and the data that other contexts need:

```python
@sales.event(part_of=Customer)
class CustomerRegistered:
    customer_id: Identifier(required=True)
    name: String(required=True)
    email: String(required=True)


@sales.event(part_of=Customer)
class CustomerEmailUpdated:
    customer_id: Identifier(required=True)
    new_email: String(required=True)


@sales.event(part_of=Customer)
class CustomerDeactivated:
    customer_id: Identifier(required=True)
    reason: String()
```

### Delta Events vs. Fact Events

You have two choices for how events carry state across context boundaries:

**Delta events** describe what changed. They are lightweight and precise, but
consuming contexts must process every event type and build up state incrementally:

```python
# Consumer must handle each event type to build local state
@handle(CustomerRegistered)
def on_registered(self, event): ...

@handle(CustomerEmailUpdated)
def on_email_updated(self, event): ...

@handle(CustomerAddressUpdated)
def on_address_updated(self, event): ...
```

**Fact events** carry the complete aggregate state at a point in time. Consumers
get a full snapshot with every event, simplifying their logic:

```python
# Sales context: enable fact events
@sales.aggregate(fact_events=True)
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True, max_length=100)
    email: String(required=True)
    segment: String(choices=CustomerSegment, default="STANDARD")
```

With `fact_events=True`, Protean automatically generates a fact event containing
the full aggregate state whenever the aggregate changes. Consuming contexts
simply overwrite their local representation with the latest snapshot.

**When to use which:**

| Approach | Best for |
|----------|----------|
| Delta events | Internal consumption within a bounded context, event sourcing, fine-grained reactions to specific changes |
| Fact events | Cross-context state transfer, building read models in other contexts, reducing consumer complexity |

For connecting concepts across bounded contexts, **fact events are the
recommended default**. They implement the Event-Carried State Transfer pattern,
keeping consumers simple and resilient to schema evolution in the source context.

---

## Step 3: Consume Events and Build Local Models

Each consuming context listens to the source context's events and maintains its
own representation. The mechanism depends on whether the contexts share the same
Protean domain or communicate through an external broker.

### Same Domain: Event Handlers with Cross-Aggregate Streams

When multiple aggregates exist within the same Protean domain, use event handlers
with the `stream_category` option to listen across aggregate boundaries:

```python
@domain.aggregate
class Customer:
    """Authority for customer lifecycle."""
    customer_id: Auto(identifier=True)
    name: String(required=True)
    email: String(required=True)


@domain.aggregate
class BillingAccount:
    """Billing context's local model of a customer."""
    account_id: Auto(identifier=True)
    customer_id: Identifier(required=True)  # Correlation ID
    email: String(required=True)
    account_status: String(default="ACTIVE")


@domain.event_handler(part_of=BillingAccount, stream_category="customer")
class BillingAccountLifecycleHandler:
    """Reacts to Customer lifecycle events to manage billing accounts."""

    @handle(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        repo = current_domain.repository_for(BillingAccount)
        account = BillingAccount(
            customer_id=event.customer_id,  # Correlation
            email=event.email,
            account_status="ACTIVE",
        )
        repo.add(account)

    @handle(CustomerDeactivated)
    def on_customer_deactivated(self, event: CustomerDeactivated):
        repo = current_domain.repository_for(BillingAccount)
        account = repo._dao.find_by(customer_id=event.customer_id)
        account.suspend()
        repo.add(account)
```

The event handler is `part_of` the `BillingAccount` aggregate but subscribes to
the `customer` stream category. It translates Customer events into
BillingAccount operations, using `customer_id` as the correlation identifier.

### Separate Domains: Subscribers as Anti-Corruption Layers

When bounded contexts are deployed as separate services communicating through a
message broker, use subscribers. Subscribers receive raw payloads from external
systems and translate them into the local domain's language:

```python
# Shipping context -- separate domain
shipping = Domain(__file__, "Shipping")


@shipping.aggregate
class Recipient:
    """Shipping context's model of a customer."""
    recipient_id: Auto(identifier=True)
    customer_id: Identifier(required=True)  # Correlation ID
    name: String(required=True)
    delivery_address = ValueObject(Address)


@shipping.subscriber(stream="sales_customer_events")
class CustomerEventSubscriber:
    """Consumes customer events from the Sales context's broker stream.

    Acts as an anti-corruption layer: translates Sales' customer schema
    into Shipping's Recipient model.
    """

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type", "")

        if "CustomerRegistered" in event_type:
            self._handle_registration(payload)
        elif "CustomerAddressUpdated" in event_type:
            self._handle_address_update(payload)

    def _handle_registration(self, payload: dict) -> None:
        repo = shipping.repository_for(Recipient)
        recipient = Recipient(
            customer_id=payload["customer_id"],
            name=payload["name"],
            delivery_address=Address(
                street=payload.get("street", ""),
                city=payload.get("city", ""),
                zip_code=payload.get("zip_code", ""),
            ),
        )
        repo.add(recipient)

    def _handle_address_update(self, payload: dict) -> None:
        repo = shipping.repository_for(Recipient)
        recipient = repo._dao.find_by(
            customer_id=payload["customer_id"]
        )
        recipient.update_address(
            Address(
                street=payload["street"],
                city=payload["city"],
                zip_code=payload["zip_code"],
            )
        )
        repo.add(recipient)
```

The subscriber is the **anti-corruption layer**. It prevents the Sales context's
schema from leaking into the Shipping domain. If Sales changes how it structures
customer events, only the subscriber needs to change -- the `Recipient` aggregate
and the rest of the Shipping domain remain untouched.

### Cross-Context Projections

For read-only views that combine data from multiple aggregates or contexts,
use projectors. Projectors can subscribe to multiple stream categories
simultaneously:

```python
@domain.projection
class CustomerDashboard:
    """Read model combining data from Customer and BillingAccount."""
    customer_id: Identifier(identifier=True)
    name: String()
    email: String()
    account_status: String()
    total_invoiced: Float(default=0.0)


@domain.projector(
    projector_for=CustomerDashboard,
    stream_categories=["customer", "billing_account"]
)
class CustomerDashboardProjector:

    @on(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        dashboard = CustomerDashboard(
            customer_id=event.customer_id,
            name=event.name,
            email=event.email,
        )
        current_domain.repository_for(CustomerDashboard).add(dashboard)

    @on(InvoiceIssued)
    def on_invoice_issued(self, event: InvoiceIssued):
        repo = current_domain.repository_for(CustomerDashboard)
        dashboard = repo.get(event.customer_id)
        dashboard.total_invoiced += event.amount
        repo.add(dashboard)
```

Projections are ideal for query scenarios that span multiple aggregates. They
are read-optimized, denormalized, and eventually consistent -- exactly what you
need for cross-context views.

---

## The Correlation ID

The shared identifier -- the correlation ID -- is the linchpin of this pattern.
Every context stores it on its local model and uses it to connect incoming events
to the right local entity.

### Design Guidelines

**Use the source context's identity.** The context that owns the concept generates
its identity. All other contexts store this identity as a reference:

```python
# Sales (authority): customer_id is the primary identity
class Customer:
    customer_id: Auto(identifier=True)

# Billing (consumer): customer_id is a stored reference
class BillingAccount:
    account_id: Auto(identifier=True)       # Own identity
    customer_id: Identifier(required=True)   # Correlation to Sales
```

**Embed it in every event.** Every event that crosses context boundaries must
carry the correlation ID. Without it, the consuming context cannot route the event
to the right local entity:

```python
class CustomerEmailUpdated:
    customer_id: Identifier(required=True)  # Always present
    new_email: String(required=True)
```

**Index it for efficient lookup.** Consuming contexts will frequently query by
the correlation ID. Ensure the field is indexed in whatever persistence layer
backs the local model.

### Multiple Correlation IDs

Complex workflows may involve concepts from several source contexts. A local model
can carry multiple correlation IDs:

```python
@domain.aggregate
class Shipment:
    shipment_id: Auto(identifier=True)
    order_id: Identifier(required=True)     # Correlates to Order context
    customer_id: Identifier(required=True)  # Correlates to Sales context
    warehouse_id: Identifier(required=True) # Correlates to Inventory context
```

Each identifier traces back to a different authoritative context. Events from any
of these contexts can be routed to the correct `Shipment` instance using the
appropriate correlation ID.

---

## Event Propagation Patterns

### Initialize on Creation

When a concept is created in the source context, consuming contexts create their
own local representation. The creation event must carry enough data for the
consumer to initialize its model:

```python
# Source raises:
CustomerRegistered(
    customer_id="c-123",
    name="Jane Doe",
    email="jane@example.com",
)

# Billing consumer creates:
BillingAccount(
    customer_id="c-123",    # From event
    email="jane@example.com",  # From event
    account_status="ACTIVE",   # Billing's own default
)
```

### Propagate Lifecycle Changes

After initialization, the source context publishes events for changes that other
contexts care about. Each consumer decides which events are relevant and how
to react:

```python
# Source raises: CustomerDeactivated
# Billing reacts: Suspend the account
# Shipping reacts: Cancel pending deliveries
# Support reacts: Close open tickets
```

Not every consumer reacts to every event. Billing may not care about
`CustomerAddressUpdated`, while Shipping certainly does. Each consumer subscribes
to what it needs and ignores the rest.

### Use Read Models Where Appropriate

Sometimes a consuming context doesn't need a full aggregate -- it only needs a
read-only reference for display or validation. Use projections for these
scenarios:

```python
@domain.projection
class CustomerReference:
    """Read-only reference to a customer, built from Sales events."""
    customer_id: Identifier(identifier=True)
    name: String()
    email: String()
    is_active: Boolean(default=True)
```

Projections are simpler than aggregates. They have no business logic, no
invariants, and no lifecycle. They are just data, kept up-to-date by a projector
that listens to the source context's stream.

---

## What to Avoid

### Querying Across Context Boundaries

A consuming context should never call the source context's API to get current
state. The source's state may have already changed between the query and the
consumer's use of the data:

```python
# Anti-pattern: querying Sales from Billing
def create_billing_account(self, customer_id):
    # DON'T DO THIS
    customer = sales_api.get_customer(customer_id)
    account = BillingAccount(
        customer_id=customer.id,
        email=customer.email,  # May already be stale
    )
```

Instead, consume events and maintain local state. The local copy may be
*eventually* consistent, but it is **self-contained** and does not create runtime
coupling.

### Sharing Domain Classes Across Contexts

Two contexts should never import the same aggregate or entity class. Each context
has its own model, shaped by its own Ubiquitous Language:

```python
# Anti-pattern: shared class
from sales.domain import Customer  # DON'T import across contexts

# Correct: each context defines its own model
# Sales has Customer, Billing has BillingAccount, Shipping has Recipient
```

Even if the models look similar today, they will diverge as each context evolves.
Sharing a class couples their evolution paths.

### Treating Events as Remote Procedure Calls

Events are facts, not requests. A publishing context should not expect or depend
on a consuming context's reaction. The publisher raises `CustomerRegistered` and
moves on. Whether Billing creates an account, Support creates a contact, or no
one reacts at all -- the publisher doesn't know and doesn't care.

If you need a guaranteed response from another context, use a command-based
integration (e.g., an API call or a command sent through a broker), not events.

---

## Summary

| Aspect | Approach |
|--------|----------|
| Shared identity | Use the source context's identity as a correlation ID in all consuming contexts |
| State propagation | Publish lifecycle events from the authoritative context; consume and build local models |
| Within same domain | Event handlers with `stream_category` override for cross-aggregate subscriptions |
| Across separate domains | Subscribers on broker streams, acting as anti-corruption layers |
| Read-only cross-context views | Projections built by projectors subscribing to multiple stream categories |
| Event format for cross-context transfer | Fact events (`fact_events=True`) for complete state snapshots |
| Schema isolation | Each context maintains its own model; subscribers translate between schemas |
| Querying across boundaries | Avoid; build local read models from events instead |

The pattern is rooted in a core DDD principle: **bounded contexts are
autonomous**. They own their models, their data, and their rules. The only thing
they share is identity and events. This keeps contexts loosely coupled while
ensuring they stay synchronized on the real-world concepts they all model.

---

!!! tip "Related reading"
    **Concepts:**

    - [Events](../concepts/building-blocks/events.md) — Events as the communication mechanism between domains.
    - [Subscribers](../concepts/building-blocks/subscribers.md) — Consuming messages from external bounded contexts.

    **Guides:**

    - [Subscribers](../guides/consume-state/subscribers.md) — Defining subscribers for external message consumption.
    - [Events](../guides/domain-definition/events.md) — Event definition and structure.
