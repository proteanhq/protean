# Connecting Concepts Across Bounded Contexts

## The Problem

In a non-trivial system, the same real-world concept inevitably appears in
multiple bounded contexts. A "Customer" exists in Sales, Billing, Shipping, and
Support, but each context cares about different attributes, enforces different
rules, and evolves at its own pace.

This creates a tension:

- **The contexts need to know about each other's state**: When Sales registers a
  new customer, Billing needs to create an account. When Billing suspends an
  account, Support needs to know. When Shipping updates an address, Sales may want
  to reflect it.
- **The contexts must not be coupled**: If Billing directly queries the Sales
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
--8<-- "patterns/connect-concepts-across-domains/002.py:sales-customer"
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
--8<-- "patterns/connect-concepts-across-domains/002.py:sales-events"
```

### Delta Events vs. Fact Events

You have two choices for how events carry state across context boundaries:

**Delta events** describe what changed. They are lightweight and precise, but
consuming contexts must process every event type and build up state incrementally:

```python
# fragment
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
--8<-- "patterns/connect-concepts-across-domains/003.py:fact-events"
```

With `fact_events=True`, Protean automatically generates a fact event containing
the full aggregate state whenever the aggregate changes. Consuming contexts
overwrite their local representation with the latest snapshot.

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
own representation. The mechanism depends on the deployment relationship between
the contexts.

!!!tip "Choosing the right integration mechanism"
    **Same domain:** Use an event handler on the aggregate that raises the
    event, and have it issue a command to the other aggregate for simple state
    sync.

    **Co-located domains:** Use event handlers with `stream_category` for
    simple state sync, or `register_external_event()` with process managers
    for multi-step cross-domain workflows.

    **Distributed domains:** Use subscribers as anti-corruption layers.

    See [Multi-Domain Applications, Cross-domain
    communication](../guides/multi-domain-applications.md#cross-domain-communication)
    for the full decision framework.

### Same Domain: An Event Handler That Issues Commands

When multiple aggregates exist within the same Protean domain, the event
handler stays with the aggregate that raises the events. It issues a command
for each change the other aggregate must make, and that aggregate's command
handler does the write:

```python
--8<-- "patterns/connect-concepts-across-domains/001.py:same-domain-events"
--8<-- "patterns/connect-concepts-across-domains/001.py:same-domain"
```

The event handler is `part_of` the `Customer` aggregate and reads the
`customer` stream, where the events are raised. It translates Customer events
into BillingAccount commands, using `customer_id` as the correlation
identifier. `BillingAccount` changes only through its own command handler.

Events are delivered at least once, so the same event can arrive twice. The
command handler skips a redelivered command: it opens no second account for a
customer, and it leaves an account that is already suspended as it is. The
check reads before it writes, so it does not stop two copies of
`OpenBillingAccount` that are handled at the same moment by parallel workers.

The two commands are separate messages. If `OpenBillingAccount` fails and is
retried, `SuspendBillingAccount` can be processed before the account is stored.
Then `find_by` raises `ObjectNotFoundError` and the command fails. The server
retries a failed message, and by then the account usually exists. See
[Error Handling](../guides/server/error-handling.md) for the retry settings.

### Separate Domains: Subscribers as Anti-Corruption Layers

When bounded contexts are deployed as separate services communicating through a
message broker, use subscribers. Subscribers receive raw payloads from external
systems and translate them into the local domain's language:

```python
--8<-- "patterns/connect-concepts-across-domains/004.py:shipping"
```

The subscriber is the **anti-corruption layer**. It prevents the Sales
context's schema from leaking into the Shipping domain. If Sales changes how it
structures customer events, only the subscriber needs to change, the `Recipient`
aggregate and the rest of the Shipping domain remain untouched.

### Cross-Context Projections

For read-only views that combine data from multiple aggregates or contexts,
use projectors. Projectors can subscribe to multiple stream categories
simultaneously:

```python
--8<-- "patterns/connect-concepts-across-domains/005.py:dashboard"
```

Projections are ideal for query scenarios that span multiple aggregates. They
are read-optimized, denormalized, and eventually consistent, exactly what you
need for cross-context views.

---

## The Correlation ID

The shared identifier, the correlation ID, is what holds this pattern together.
Every context stores it on its local model and uses it to connect incoming
events to the right local entity.

### Design Guidelines

**Use the source context's identity.** The context that owns the concept generates
its identity. All other contexts store this identity as a reference:

```python
# fragment
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
# fragment
class CustomerEmailUpdated:
    customer_id: Identifier(required=True)  # Always present
    new_email: String(required=True)
```

**Index it for efficient lookup.** Consuming contexts will frequently query by
the correlation ID. Make sure the field is indexed in whatever persistence layer
backs the local model.

### Multiple Correlation IDs

Complex workflows may involve concepts from several source contexts. A local model
can carry multiple correlation IDs:

```python
--8<-- "patterns/connect-concepts-across-domains/006.py:shipment"
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
# fragment
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
# fragment
# Source raises: CustomerDeactivated
# Billing reacts: Suspend the account
# Shipping reacts: Cancel pending deliveries
# Support reacts: Close open tickets
```

Not every consumer reacts to every event. Billing may not care about
`CustomerAddressUpdated`, while Shipping certainly does. Each consumer subscribes
to what it needs and ignores the rest.

### Use Read Models Where Appropriate

Sometimes a consuming context doesn't need a full aggregate. It only needs a
read-only reference for display or validation. Use projections for these
scenarios:

```python
--8<-- "patterns/connect-concepts-across-domains/006.py:customer-reference"
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
# fragment
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
# fragment
# Anti-pattern: shared class
from sales.domain import Customer  # DON'T import across contexts

# Correct: each context defines its own model
# Sales has Customer, Billing has BillingAccount, Shipping has Recipient
```

Even if the models look similar today, they will diverge as each context evolves.
Sharing a class couples their evolution paths.

### Treating Events as Remote Procedure Calls

Events are facts, not requests. A publishing context should not expect or
depend on a consuming context's reaction. The publisher raises
`CustomerRegistered` and moves on. Whether Billing creates an account, Support
creates a contact, or no one reacts at all. The publisher doesn't know and
doesn't care.

If you need a guaranteed response from another context, use a command-based
integration (e.g., an API call or a command sent through a broker), not events.

---

## Summary

| Aspect | Approach |
|--------|----------|
| Shared identity | Use the source context's identity as a correlation ID in all consuming contexts |
| State propagation | Publish lifecycle events from the authoritative context; consume and build local models |
| Within same domain | An event handler on the aggregate that raises the event issues a command to the other aggregate |
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

    - [Events](../concepts/building-blocks/events.md): Events as the communication mechanism between domains.
    - [Subscribers](../concepts/building-blocks/subscribers.md): Consuming messages from external bounded contexts.

    **Guides:**

    - [Subscribers](../guides/consume-state/subscribers.md): Defining subscribers for external message consumption.
    - [Events](../guides/domain-definition/events.md): Event definition and structure.
