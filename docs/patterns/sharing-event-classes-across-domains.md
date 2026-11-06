# Sharing Event Classes Across Domains

## The Problem

Two domains (Order and Fulfillment) communicate through events. The Order
domain raises `OrderPlaced`. The Fulfillment domain consumes it. A developer
extracts the `OrderPlaced` class into a shared library so both domains use the
same class definition:

```
shared-events/
  events/
    order_events.py    # OrderPlaced, OrderCancelled, OrderShipped

order-domain/
  requirements.txt     # depends on shared-events

fulfillment-domain/
  requirements.txt     # depends on shared-events
```

This feels clean, no duplication, one source of truth. But the shared library
couples the two domains. That coupling undermines the autonomy bounded contexts
are supposed to give each domain:

- **Release coupling**: When the Order domain needs to add a field to
  `OrderPlaced`, it must update the shared library, release a new version, and
  wait for the Fulfillment domain to upgrade. If the Fulfillment domain is
  maintained by a different team or on a different release cadence, this
  creates coordination overhead.

- **Diamond dependency**: Both domains depend on the shared library. If the
  Order domain needs version 2.0 and the Fulfillment domain is still on 1.5,
  you have a version conflict. Resolving it means either forcing the
  Fulfillment team to upgrade or maintaining backward compatibility in the
  shared library. Both add friction.

- **Conceptual coupling**: The `OrderPlaced` class now has to meet the needs of
  two domains. It must satisfy the Order domain's need to express what happened
  *and* the Fulfillment domain's need to consume it. If these needs diverge
  (Order wants to add internal fields, Fulfillment only needs a subset), the
  shared class becomes a compromise.

- **Deployment coupling**: If the shared library has a bug or a breaking
  change, both domains get the bug or the breaking change at the same time.
  Independent deployment (a key benefit of bounded contexts) is compromised.

The root cause: **sharing code across domain boundaries creates coupling that
sharing messages avoids**.

---

## The Pattern

Share **schemas** (the message contract), not **code** (the class definition).
Each domain defines its own classes that conform to the agreed-upon schema.

```
Shared (contract, not code):
  - Event name: "OrderPlaced"
  - Fields: order_id (string), customer_id (string), items (list), total (float)
  - Published on stream: "orders"

Order domain (publisher):
  @domain.event(part_of=Order)
  class OrderPlaced(BaseEvent):     # Order domain's own class
      order_id = Identifier(...)
      customer_id = Identifier(...)
      items = List(...)
      total = Float(...)

Fulfillment domain (consumer):
  @domain.event(part_of=Shipment)
  class ExternalOrderPlaced(BaseEvent):  # Fulfillment domain's own class
      order_id = Identifier(...)
      customer_id = Identifier(...)
      items = List(...)
```

Both classes read the same JSON structure. The Fulfillment class declares only
the fields Fulfillment uses, so it leaves out `total`. They don't need to be
the same Python class.

---

## Why Schemas, Not Classes

### Independent Evolution

When the Order domain adds `discount_code` to `OrderPlaced`:

- **With shared classes:** Both domains must update the shared library, both
  must redeploy.
- **With shared schemas:** The Order domain adds the field to its class. The
  Fulfillment domain's consumer keeps only the fields its own class declares.
  It skips `discount_code` until the Fulfillment domain adds the field to its
  class. Protean events reject undeclared fields by default, so the consumer
  filters the payload before building its event (see the consumer-side contract
  test below).

### Independent Deployment

Each domain owns its own class definition. A change to one domain's class
requires no edit to the other domain's codebase. Deployment is independent.

### Subset Consumption

The Fulfillment domain doesn't need every field the Order domain publishes.
With its own class, it defines only the fields it cares about:

```python
--8<-- "patterns/sharing-event-classes-across-domains/001.py:subset"
```

The Fulfillment domain keeps `order_id`, `customer_id`, and `items`. It
ignores `customer_email`, `subtotal`, `tax`, `total`, `currency`,
`discount_code`, `placed_at`, `ip_address`, and `user_agent`. It doesn't need
them and shouldn't depend on them.

---

## How to Define the Contract

### Option 1: Documentation

The simplest approach. The publishing domain documents its event schemas in
human-readable form:

!!! example "OrderPlaced Event Schema"

    Published on stream: `orders`

    | Field | Type | Required | Description |
    |-------|------|----------|-------------|
    | order_id | string (UUID) | yes | The order's unique identifier |
    | customer_id | string (UUID) | yes | The customer who placed the order |
    | items | list of objects | yes | Line items in the order |
    | items[].product_id | string | yes | Product identifier |
    | items[].quantity | integer | yes | Quantity ordered |
    | total | float | yes | Order total including tax |
    | placed_at | ISO 8601 datetime | yes | When the order was placed |

Consuming domains read the documentation and define their own classes
accordingly.

**Use it when you have** small teams, few domains, and simple event schemas.

### Option 2: JSON Schema

A machine-readable contract that can be validated automatically:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OrderPlaced",
  "type": "object",
  "required": ["order_id", "customer_id", "items", "total"],
  "properties": {
    "order_id": { "type": "string", "format": "uuid" },
    "customer_id": { "type": "string", "format": "uuid" },
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["product_id", "quantity"],
        "properties": {
          "product_id": { "type": "string" },
          "quantity": { "type": "integer", "minimum": 1 }
        }
      }
    },
    "total": { "type": "number", "minimum": 0 }
  }
}
```

Each domain validates its events against the schema in tests, ensuring
compatibility without sharing code.

**Use it when you need** formal integration contracts and CI/CD validation
across multiple teams.

### Option 3: Schema Registry

For large-scale systems, a centralized schema registry stores event schemas
and enforces compatibility rules:

- New event versions must be backward-compatible with the previous version
- Consumers can discover available events and their schemas
- Schema evolution is tracked and versioned

**Use it when you have** many domains, multiple teams, and strict compatibility
requirements.

---

## Contract Testing

Instead of sharing code, use **contract tests** to verify that the publisher's
events match what consumers expect:

### Publisher-Side Contract Test

```python
--8<-- "patterns/sharing-event-classes-across-domains/002.py:publisher_test"
```

### Consumer-Side Contract Test

```python
--8<-- "patterns/sharing-event-classes-across-domains/003.py:consumer_test"
```

Each domain runs its contract test independently. Both tests check against the
agreed contract. The publisher's test fails if its event stops carrying a
contract field. The consumer's test fails if its class can no longer read a
payload in the contract's shape. Neither test needs shared code.

---

## When Sharing Code Is Acceptable

### Intentional Shared Kernel

In DDD, the **Shared Kernel** pattern means two bounded contexts explicitly
agree to share a subset of their domain model. This is appropriate when:

- Both contexts are owned by the same team
- They share the same deployment pipeline
- The shared concepts are stable and rarely change
- The coupling is intentional and documented

```python
--8<-- "patterns/sharing-event-classes-across-domains/004.py:shared_kernel"
```

A shared kernel is a conscious architectural decision, not an accidental
dependency. It should be small, stable, and explicitly agreed upon by both
teams.

### Same Deployment Unit

Some pairs of domains always deploy together (e.g., a monolith with logical
bounded contexts). For those domains, sharing event classes adds no deployment
coupling, because their deployments are already coupled. The overhead of
maintaining separate classes may not be worth it.

Protean supports domains in the same deployment unit with
`register_external_event()`. Each domain defines its own event class and
registers it with the external event's type string. Neither domain imports code
from the other. You still get typed events and IDE support:

```python
--8<-- "patterns/sharing-event-classes-across-domains/005.py:external_event"
```

`register_external_event()` gives you the benefits of typed events (validation,
autocomplete, handler signatures). The domains share the contract as a schema
(the type string) and share no code (no shared import).

See [Multi-Domain Applications, Cross-domain
communication](../guides/multi-domain-applications.md#cross-domain-communication)
for the full guidance on when to use `register_external_event()` and when to
use subscribers.

### Protobuf / Avro Definitions

When you use schema-first serialization formats (Protocol Buffers, Avro), a
code generator builds each domain's classes from the schema. Both domains use
generated classes derived from the same schema definition, which is a form of
schema-sharing, not code-sharing.

---

## Anti-Patterns

### Accidental Shared Kernel

```text
# Anti-pattern: sharing evolved into a large shared library
shared-events/
  events/
    order_events.py      # 15 event classes
    customer_events.py   # 12 event classes
    inventory_events.py  # 8 event classes
    payment_events.py    # 10 event classes
    utils.py             # Helper functions
    validators.py        # Shared validation
```

One shared event class grew into a large shared library. Every domain now
depends on that library. A change to any file in the library changes the code
that every domain runs. This is an accidental shared kernel, coupling by
convenience, not by design.

### Exposing Internal Events

```python
# fragment
# Anti-pattern: sharing events that include internal details
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True)
    # Internal implementation details shared with consumers
    _processing_flags: Dict()
    _audit_trail: List()
    _internal_status: String()
```

Only publish events with fields that consumers should see. Internal details
belong to the publishing domain and should not be part of the public contract.

---

## Summary

| Approach | Coupling | Independence | Best For |
|----------|---------|-------------|----------|
| Shared classes (library) | High | Low | Same team, same deploy |
| Shared schemas (documented) | Low | High | Multiple teams, simple events |
| JSON Schema / contract tests | Low | High | Formal integration, CI/CD |
| Schema registry | Low | Very High | Large-scale, many domains |
| Intentional shared kernel | Medium | Medium | Stable, agreed-upon concepts |

Domains communicate through messages, not through shared code. Each domain
defines its own classes that conform to the agreed-upon schema. Share the
contract (schema), not the implementation (classes). Use contract tests to
verify compatibility without code dependencies.

---

!!! tip "Related reading"
    **Concepts:**

    - [Events](../concepts/building-blocks/events.md): Event structure and cross-domain communication.

    **Guides:**

    - [Events](../guides/domain-definition/events.md): Defining events, metadata, and versioning.
