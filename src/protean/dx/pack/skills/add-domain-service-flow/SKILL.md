---
name: add-domain-service-flow
description: Build a domain service flow in Protean for business logic that spans two or more aggregates. Domain services are stateless, encapsulate cross-aggregate business rules, and run pre/post invariants for validation. They are used when business logic doesn't naturally belong to a single aggregate. Wire them into command handlers or application services for persistence. Use when the user asks to "add a domain service", "implement cross-aggregate logic", "coordinate multiple aggregates", "add a business operation spanning aggregates", "validate across aggregates", or when they describe scenarios like "placing an order checks inventory and reserves stock", "transferring funds between accounts", "scheduling involves both resource and calendar".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [domain-service, aggregate, command-handler]
---

# Add Domain Service Flow

A domain service encapsulates business logic that spans multiple aggregates. It is stateless, operates on aggregates passed to it, and validates cross-aggregate invariants.

## When domain services fit

Use a domain service when:
- Business logic involves **two or more aggregates**
- The logic **doesn't naturally belong** to either aggregate
- You need **cross-aggregate validation** before executing

Do NOT use for:
- Logic that belongs to a single aggregate → use an aggregate method
- Orchestration and persistence → use a command handler
- Authorization and context checks → use handler guards (Layer 4)

## What this creates

| Component | Purpose | Decorator |
|-----------|---------|-----------|
| Domain service | Cross-aggregate business logic + validation | `@domain.domain_service(part_of=[Agg1, Agg2])` |
| Pre invariants | Validate preconditions across aggregates | `@invariant.pre` on service |
| Command handler | Orchestrate: load aggregates → run service → persist | `@domain.command_handler(part_of=...)` |

## Information to gather

Before building a domain service flow:

- [ ] **What aggregates are involved?** — Which 2+ aggregates participate?
- [ ] **What is the cross-aggregate rule?** — Business logic that spans boundaries
- [ ] **What preconditions must hold?** — Pre-invariants to check before executing
- [ ] **Who calls the service?** — Command handler or application service
- [ ] **Who persists the results?** — The calling handler (not the service itself)

## Process

### Step 1: Define the domain service

Use the callable pattern: `__init__` accepts aggregates, `__call__` executes the logic.

```python
from protean.core.domain_service import BaseDomainService

@domain.domain_service(part_of=[Order, Inventory])
class PlaceOrderService:
    def __init__(self, order, inventories):
        BaseDomainService.__init__(self, *(order, inventories))
        self.order = order
        self.inventories = inventories

    def __call__(self):
        for item in self.order.items:
            inv = next(i for i in self.inventories if i.product_id == item.product_id)
            inv.reserve_stock(item.quantity)
        self.order.confirm()
```

**Key rules:**
- `part_of=[Agg1, Agg2]` — list all aggregates the service spans
- Call `BaseDomainService.__init__(self, *(aggregates))` — required for invariant support
- `__call__` executes the business logic — mutates aggregates
- Service is **stateless** — no persistence, no side effects beyond aggregate mutation

### Step 2: Add pre/post invariants

Pre-invariants validate before execution. Post-invariants validate after.

```python
@invariant.pre
def sufficient_stock(self):
    for item in self.order.items:
        inv = next((i for i in self.inventories if i.product_id == item.product_id), None)
        if inv is None or inv.quantity < item.quantity:
            raise ValidationError({"_service": ["Insufficient stock"]})

@invariant.post
def all_stock_reserved(self):
    # Validate post-conditions
    ...
```

### Step 3: Wire into a command handler

The command handler is responsible for loading aggregates, running the service, and persisting results.

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command):
        order = domain.repository_for(Order).get(command.order_id)
        inventories = [
            domain.repository_for(Inventory)._dao.find_by(product_id=item.product_id)
            for item in order.items
        ]

        # Run domain service (pre checks → logic → post checks)
        PlaceOrderService(order, inventories)()

        # Persist all affected aggregates
        domain.repository_for(Order).add(order)
        for inv in inventories:
            domain.repository_for(Inventory).add(inv)
```

**Important:** The command handler persists, not the service. This keeps the service focused on business logic.

## The callable pattern

```python
# Instantiate with aggregates, then call
service = PlaceOrderService(order, inventories)
service()  # Runs: pre invariants → __call__ → post invariants
```

The `BaseDomainService.__init__` call is required. Use the explicit form (not `super()`) because the `@domain.domain_service` decorator modifies the class.

## Domain service vs other patterns

| Pattern | Scope | Persistence | Use case |
|---------|-------|-------------|----------|
| Aggregate method | Single aggregate | Via handler | Logic belonging to one aggregate |
| Domain service | Multiple aggregates | Via handler | Cross-aggregate business rules |
| Command handler | Orchestration | Yes (repository) | Loading, wiring, persisting |
| Event handler | Reaction | Yes (repository) | Async side effects |

## Common mistakes

### Persisting inside the domain service

```python
# Wrong! The service persists
class PlaceOrderService:
    def __call__(self):
        ...
        current_domain.repository_for(Order).add(self.order)  # No
```

Instead: keep the service stateless; the calling command handler persists the affected aggregates.

### Using a domain service for single-aggregate logic

```python
# Wrong! Only one aggregate is involved
@domain.domain_service(part_of=[Order])
class CancelOrderService:
    ...
```

Instead: put single-aggregate logic on the aggregate itself; reach for a domain service only when 2+ aggregates participate.

### Skipping BaseDomainService.__init__

```python
# Wrong! Invariants won't be wired up
@domain.domain_service(part_of=[Order, Inventory])
class PlaceOrderService:
    def __init__(self, order, inventories):
        self.order = order  # missing BaseDomainService.__init__
        self.inventories = inventories
```

Instead: call `BaseDomainService.__init__(self, *(order, inventories))` so pre/post invariants run.

### Calling logic directly instead of via `__call__`

```python
service = PlaceOrderService(order, inventories)
service.run()  # Wrong! Bypasses pre/post invariants
```

Instead: invoke the instance — `service()` — so invariants execute around the logic.

## Complete examples

- [Basic domain service](assets/domain_service_flow_basic.py) — Fund transfer between two accounts with validation
- [Domain service in handler](assets/domain_service_flow_in_handler.py) — Order placement wired through a command handler
- [Domain service with invariants](assets/domain_service_flow_invariants.py) — Pre and post invariants for cross-aggregate validation

## Detailed references

- [Domain Service Patterns](references/domain-service-patterns.md) — Callable, instance method, and class method patterns
- [When to Use](references/when-to-use.md) — Decision guide for choosing domain services vs other patterns

## Related skills

- [domain-service](../domain-service/SKILL.md) — Domain service definition and patterns
- [aggregate](../aggregate/SKILL.md) — Aggregates that domain services coordinate
- [command-handler](../command-handler/SKILL.md) — Wiring domain services into command flows
- [add-validation](../add-validation/SKILL.md) — Invariants on domain services (Layer 3+)
