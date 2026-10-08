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
| Domain service | Cross-aggregate validation + the change to the primary aggregate | `@domain.domain_service(part_of=[Agg1, Agg2])` |
| Pre/post invariants | Validate conditions across aggregates | `@invariant.pre` / `@invariant.post` on service |
| Command handler | Load aggregates → run service → persist the primary aggregate | `@domain.command_handler(part_of=Agg1)` |
| Event handler | React to the primary aggregate's event and issue a command to the other aggregate | `@domain.event_handler(part_of=Agg1)` |
| Command handler | Apply the change to the other aggregate, once | `@domain.command_handler(part_of=Agg2)` |

## One aggregate per transaction

A domain service reads several aggregates, but a handler persists only one of them. The service checks the rule across all the aggregates and changes only the **primary** aggregate, the one the command belongs to. The command handler persists that aggregate. The primary aggregate raises an event, and an event handler in its cluster issues a command to the other aggregate. That aggregate's command handler applies the change in a transaction separate from the primary aggregate's. With async command processing, the default, the command handler commits on its own. With sync command processing, it joins the event handler's transaction.

So the validation is atomic: the service checks every aggregate in one step, before anything changes. The change to the other aggregate is eventually consistent: it happens after the primary aggregate commits, and there is a short window where the two disagree.

A Unit of Work is one real database transaction, and it can hold changes to several aggregates. "One aggregate per transaction" is a design rule; the Unit of Work does not enforce it. See ADR-0027 ([The Unit of Work is a real database transaction](https://docs.proteanhq.com/adr/0027-unit-of-work-is-a-real-transaction/)) and ADR-0031 ([A handler method persists or calls out, never both](https://docs.proteanhq.com/adr/0031-handlers-persist-or-call-out/)).

## Information to gather

Before building a domain service flow:

- [ ] **What aggregates are involved?**: Which 2+ aggregates participate?
- [ ] **Which aggregate is primary?**: The one the command belongs to and the service changes
- [ ] **What is the cross-aggregate rule?**: Business logic that spans boundaries
- [ ] **What preconditions must hold?**: Pre-invariants to check before executing
- [ ] **Who calls the service?**: Command handler or application service
- [ ] **How do the other aggregates change?**: Through an event and a command, applied once

## Process

The examples on this page use these aggregates, commands, and events:

```python
@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.aggregate
class Order:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    status: String(default="pending")

    def confirm(self):
        self.status = "confirmed"
        self.raise_(
            OrderConfirmed(
                order_id=self.id,
                product_id=self.product_id,
                quantity=self.quantity,
            )
        )


@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    available: Integer(default=0)
    reserved_order_ids: List(content_type=String)

    def reserve_stock(self, order_id, quantity):
        self.available -= quantity
        self.reserved_order_ids = [*self.reserved_order_ids, order_id]


@domain.command(part_of="Order")
class PlaceOrder:
    order_id: Identifier(required=True)


@domain.command(part_of="Inventory")
class ReserveStock:
    order_id: Identifier(required=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

### Step 1: Define the domain service

Use the callable pattern: `__init__` accepts aggregates, `__call__` executes the logic.

```python
@domain.domain_service(part_of=[Order, Inventory])
class PlaceOrderService:
    def __init__(self, order, inventory):
        self.order = order
        self.inventory = inventory

    def __call__(self):
        self.order.confirm()
```

**Key rules:**
- `part_of=[Agg1, Agg2]`: list the aggregate classes the service spans
- A plain `__init__` is enough. The invariants are wired when the service is registered, so you do not need to call the base class `__init__`
- `__call__` executes the business logic and changes only the primary aggregate (here, the Order)
- Service is **stateless**: no persistence, no side effects beyond the aggregate change

### Step 2: Add pre/post invariants

Pre-invariants validate before execution. Post-invariants validate after. Add them as methods on the service:

```python
# fragment
    @invariant.pre
    def sufficient_stock(self):
        if self.inventory.available < self.order.quantity:
            raise ValidationError({"_service": ["Insufficient stock"]})

    @invariant.post
    def order_is_confirmed(self):
        if self.order.status != "confirmed":
            raise ValidationError({"_service": ["Order was not confirmed"]})
```

Invariants run around **every public method** of the service, including `__call__`. If one public method calls another, the invariants run again for the inner call. Name helper methods with a leading `_` so they are not wrapped. An invariant must never call a public method: that method's wrapper runs the invariant again, which calls the method again, until Python's recursion limit stops the call.

### Step 3: Wire into a command handler

The command handler loads the aggregates, runs the service, and persists the primary aggregate.

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command):
        order_repo = current_domain.repository_for(Order)
        order = order_repo.get(command.order_id)
        inventory = current_domain.repository_for(Inventory).find_by(
            product_id=order.product_id
        )

        # Run domain service (pre checks → logic → post checks)
        PlaceOrderService(order, inventory)()

        # Persist only the aggregate the service changed
        order_repo.add(order)
```

**Important:** The command handler persists, not the service. It persists only the Order; the Inventory was read for the check and is changed in Step 4.

### Step 4: Change the other aggregate through an event

An event handler in the Order's cluster reacts to `OrderConfirmed` and issues a command that belongs to Inventory. Inventory's command handler applies the change and skips an order it has already applied, because an event can be delivered more than once.

```python
@domain.event_handler(part_of=Order)
class ReserveConfirmedStock:
    @handle(OrderConfirmed)
    def on_order_confirmed(self, event):
        current_domain.process(
            ReserveStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveStock)
    def reserve_stock(self, command):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(product_id=command.product_id)
        if command.order_id in inventory.reserved_order_ids:
            return  # already applied; reserving again would double count
        inventory.reserve_stock(command.order_id, command.quantity)
        repo.add(inventory)
```

- `part_of=Order`: the event handler sits in the cluster that owns `OrderConfirmed`, with no `stream_category`
- The command carries the order id from the event, so a redelivered event reissues the same command and the handler can tell it is a repeat

This is the cross-aggregate pattern from the [event-handler](../event-handler/SKILL.md) skill.

## The callable pattern

```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(product_id="SKU-1", quantity=2)
    inventory = Inventory(product_id="SKU-1", available=5)

    # Instantiate with aggregates, then call
    service = PlaceOrderService(order, inventory)
    service()  # Runs: pre invariants → __call__ → post invariants
    assert order.status == "confirmed"
```

You can still call `super().__init__(order, inventory)` in `__init__`. It stores the aggregates on `self._aggregates`; it is not needed for the invariants.

## Domain service vs other patterns

| Pattern | Scope | Persistence | Use case |
|---------|-------|-------------|----------|
| Aggregate method | Single aggregate | Via handler | Logic belonging to one aggregate |
| Domain service | Multiple aggregates | Via handler | Cross-aggregate business rules |
| Command handler | Orchestration | Yes (repository) | Loading, wiring, persisting one aggregate |
| Event handler | Reaction | No (issues a command) | Changing another aggregate after an event |

## Common mistakes

### Persisting inside the domain service

```python
# fragment
# Wrong! The service persists
class PlaceOrderService:
    def __call__(self):
        self.order.confirm()
        current_domain.repository_for(Order).add(self.order)  # No
```

Instead: keep the service stateless; the calling command handler persists the primary aggregate.

### Persisting every aggregate the service touched

```python
# fragment
# Wrong! Two aggregates in one handler
@handle(PlaceOrder)
def handle_place_order(self, command):
    ...
    PlaceOrderService(order, inventory)()
    current_domain.repository_for(Order).add(order)
    current_domain.repository_for(Inventory).add(inventory)  # No
```

Instead: change and persist only the primary aggregate, and change the other one through an event and a command (Step 4).

### Using a domain service for single-aggregate logic

```python
# fragment
# Wrong! Only one aggregate is involved
@domain.domain_service(part_of=[Order])
class CancelOrderService:
    ...
```

Instead: put single-aggregate logic on the aggregate itself; reach for a domain service only when 2+ aggregates participate.

### Calling a public helper from an invariant

```python
# fragment
# Wrong! stock_for() is public, so it is wrapped with the invariants
@domain.domain_service(part_of=[Order, Inventory])
class PlaceOrderService:
    def stock_for(self, product_id):
        return self.inventory.available

    @invariant.pre
    def sufficient_stock(self):
        if self.stock_for(self.order.product_id) < self.order.quantity:  # No
            raise ValidationError({"_service": ["Insufficient stock"]})
```

The call to `stock_for()` runs the pre-invariants again, which call `stock_for()` again, until Python's recursion limit stops the call. Instead: name the helper `_stock_for()`. Methods that start with `_` are not wrapped.

## Complete examples

- [Basic domain service](assets/domain_service_flow_basic.py): Fund transfer between two accounts: debit the source, credit the destination through an event
- [Domain service in handler](assets/domain_service_flow_in_handler.py): Course enrollment wired through a command handler, with the Student updated through an event
- [Domain service with invariants](assets/domain_service_flow_invariants.py): Pre and post invariants for cross-aggregate validation

## Detailed references

- [Domain Service Patterns](references/domain-service-patterns.md): Callable, instance method, and class method patterns
- [When to Use](references/when-to-use.md): Decision guide for choosing domain services vs other patterns

## Related skills

- [domain-service](../domain-service/SKILL.md): Domain service definition and patterns
- [aggregate](../aggregate/SKILL.md): Aggregates that domain services coordinate
- [command-handler](../command-handler/SKILL.md): Wiring domain services into command flows
- [add-validation](../add-validation/SKILL.md): Invariants on domain services (Layer 3+)

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
