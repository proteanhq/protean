# Status Transitions

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Most aggregates are state machines. An Order moves through DRAFT, PLACED,
CONFIRMED, SHIPPED, and DELIVERED. A Subscription cycles through TRIAL,
ACTIVE, PAUSED, and CANCELLED. The business rules about which transitions
are legal often define the most critical behavior in a domain.

Protean's `Status` field makes these lifecycle rules explicit and
automatically enforced.

## Defining a Status field

A `Status` field requires an Enum class as its first argument:

```python
from enum import Enum
from protean.fields import Status

class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"

@domain.aggregate
class Order:
    status = Status(OrderStatus, default="DRAFT")
```

Without a `transitions` argument, `Status` behaves like
`String(choices=OrderStatus)` — it constrains the field to valid Enum values
but does not enforce transition rules.

## Adding transitions

Pass a `transitions` dict mapping each state to its allowed next states:

```python
@domain.aggregate
class Order:
    status = Status(OrderStatus, default="DRAFT", transitions={
        OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.CANCELLED],
        OrderStatus.PLACED: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
        OrderStatus.CONFIRMED: [OrderStatus.SHIPPED],
        OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
    })
```

States **not appearing as keys** in the dict are terminal — no outgoing
transitions are allowed. In the example above, `DELIVERED` and `CANCELLED`
are terminal states.

## How enforcement works

### Direct mutation

When you assign a new status value, the framework validates the transition
immediately:

```python
order = Order()                # status = "DRAFT"
order.status = "PLACED"        # OK — DRAFT → PLACED is allowed
order.status = "SHIPPED"       # ValidationError — PLACED → SHIPPED is not allowed
```

The error message tells you exactly what's wrong:

```
ValidationError: {'status': ["Invalid status transition from 'PLACED' to 'SHIPPED'. Allowed transitions: CONFIRMED, CANCELLED"]}
```

Attempting to leave a terminal state produces a different message:

```
ValidationError: {'status': ["Invalid status transition from 'DELIVERED'. 'DELIVERED' is a terminal state with no allowed transitions"]}
```

### Same-value assignment

Setting a status to its current value is always allowed — it's a no-op, not
a transition:

```python
order.status = "DRAFT"  # No error, even if DRAFT → DRAFT is not in the map
```

### Initialization

Setting the initial value (from `None`) is always allowed, regardless of the
transition map:

```python
order = Order()           # status = "DRAFT" (via default) — OK
order = Order(status="PLACED")  # Also OK — initial assignment
```

## Working with `atomic_change`

When using `atomic_change` to batch multiple mutations, the framework captures
status snapshots on entry and validates the **start-to-end** transition on exit.
Intermediate states are not checked:

```python
from protean import atomic_change

order = Order()  # status = "DRAFT"

with atomic_change(order):
    order.status = "PLACED"
    order.amount = 100.0
# On exit: validates DRAFT → PLACED — OK
```

If the overall transition is invalid:

```python
with atomic_change(order):
    order.status = "PLACED"      # DRAFT → PLACED (valid step)
    order.status = "CONFIRMED"   # PLACED → CONFIRMED (valid step)
# On exit: validates DRAFT → CONFIRMED — NOT in DRAFT's allowed list → ValidationError
```

## Event-sourced aggregates

For event-sourced aggregates, `raise_()` wraps the `@apply` handler in
`atomic_change`. The same start-to-end validation applies:

```python
@domain.aggregate(is_event_sourced=True)
class Order:
    status = Status(OrderStatus, default="DRAFT", transitions={
        OrderStatus.DRAFT: [OrderStatus.PLACED],
        OrderStatus.PLACED: [OrderStatus.CONFIRMED],
    })

    def place(self):
        self.raise_(OrderPlaced(order_id=self.order_id))

    @apply
    def on_placed(self, event: OrderPlaced) -> None:
        self.status = "PLACED"   # Validated on atomic_change exit
```

**Event replay** (`from_events()`) does **not** validate transitions.
Replayed events are historical facts — the framework trusts them.

## Programmatic checking

Use `can_transition_to()` to check whether a transition would be valid
without actually performing it:

```python
order.can_transition_to("status", OrderStatus.SHIPPED)  # False
order.can_transition_to("status", OrderStatus.PLACED)   # True
```

This is useful for:

- Aggregate methods that want to check before raising an event
- API responses showing available actions to the client
- Conditional logic in command handlers

## Multiple status fields

An aggregate can have multiple independent `Status` fields. Each validates
its transitions independently:

```python
class PaymentStatus(Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"

class FulfillmentStatus(Enum):
    UNFULFILLED = "UNFULFILLED"
    FULFILLED = "FULFILLED"
    RETURNED = "RETURNED"

@domain.aggregate
class Order:
    payment = Status(PaymentStatus, default="PENDING", transitions={
        PaymentStatus.PENDING: [PaymentStatus.PAID],
        PaymentStatus.PAID: [PaymentStatus.REFUNDED],
    })
    fulfillment = Status(FulfillmentStatus, default="UNFULFILLED", transitions={
        FulfillmentStatus.UNFULFILLED: [FulfillmentStatus.FULFILLED],
        FulfillmentStatus.FULFILLED: [FulfillmentStatus.RETURNED],
    })
```

## Best practices

1. **Design the Enum first.** The Enum defines all possible states. Name
   values clearly — they appear in error messages and database records.

2. **Keep transition maps in the aggregate.** The transition map is business
   logic. It belongs where the business rules live.

3. **Use terminal states intentionally.** Terminal states are states with no
   outgoing transitions (absent from the map's keys). Design them as
   deliberate end-of-lifecycle markers.

4. **Combine with invariants.** `Status` handles *which* transitions are
   legal. Use `@invariant.pre` for *under what conditions* — for example,
   "can only confirm an order if payment has been received."

5. **Status on Value Objects is not allowed.** Value Objects are immutable
   and cannot transition. `Status` with `transitions` on a Value Object
   raises `IncorrectUsageError` at class creation time.

---

!!! tip "See also"
    **Reference:** [Status field](../../reference/fields/simple-fields.md#status) — Field options and argument details.

    **Related guides:**

    - [Invariants](invariants.md) — Business rules that complement transition enforcement.
    - [Aggregate Mutation](aggregate-mutation.md) — The `__setattr__` mechanism that triggers validation.
    - [Raising Events](raising-events.md) — How `raise_()` and `@apply` interact with `atomic_change`.
