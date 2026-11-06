# Model Aggregate Lifecycle as a State Machine

## The Problem

A developer adds a `status` field to an `Order` aggregate and scatters
transition logic across multiple command handlers:

```python
# fragment
from __future__ import annotations

from protean.fields import Auto, Float, Identifier, String

from protean import handle
from protean import current_domain


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float(default=0.0)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:

    @handle(PayOrder)
    def pay_order(self, command: PayOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.status = "paid"
        repo.add(order)

    @handle(ShipOrder)
    def ship_order(self, command: ShipOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.status = "shipped"
        order.tracking_number = command.tracking_number
        repo.add(order)

    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.status = "cancelled"
        repo.add(order)
```

It compiles. It passes the happy-path tests. Then things go wrong:

- **A cancelled order gets shipped**: Nothing prevents calling `ship_order`
  on an order whose status is `"cancelled"`. The handler blindly sets
  `status = "shipped"` regardless of the current state.

- **Valid states are implicit**: Is `"refund_requested"` a valid status?
  What about `"PAID"` or `"Shipped"`? Only the developer knows the set of
  allowed states. The code records it only as the strings that appear in
  handler code.

- **Transitions are invisible**: Which states can transition to which? Can a
  `"delivered"` order be cancelled? The only way to answer is to read every
  handler, every event handler, and every batch job that touches the
  `status` field.

- **Invalid transitions are silent**: When code sets `order.status = "shipped"`
  on an order in `"draft"`, the aggregate produces no error, no log and no
  event. The aggregate accepts any string. Downstream consumers then see state
  sequences that cannot happen in the business.

- **New team members guess**: A new developer adds a handler that sets `status
  = "processing"`. No consumer knows about the `"processing"` state. Nothing in
  the codebase prevents it.

The root cause: **the aggregate has a lifecycle, but the lifecycle is
encoded as ad-hoc string assignments scattered across the codebase instead
of being modeled as an explicit, enforced state machine**.

---

## The Pattern

Model the aggregate's lifecycle as an **explicit state machine** with three
components:

1. **A closed set of states**: An enum or choices list that defines every
   valid status value. No other values are possible.

2. **Named transition methods**: Each method represents one valid
   transition (e.g., `place()`, `ship()`, `cancel()`). The method name
   comes from the ubiquitous language.

3. **Pre-transition guards**: Each method checks that the aggregate is in
   a valid source state before performing the transition. Invalid
   transitions raise an error immediately.

```
States:       draft → placed → paid → shipped → delivered
                 ↓       ↓       ↓
              cancelled  cancelled  refunded

Transitions:
  place()     draft    → placed       (guard: must be draft)
  pay()       placed   → paid         (guard: must be placed)
  ship()      paid     → shipped      (guard: must be paid)
  deliver()   shipped  → delivered    (guard: must be shipped)
  cancel()    draft/placed → cancelled (guard: must be draft or placed)
  refund()    paid     → refunded     (guard: must be paid)
```

The aggregate becomes its own state machine. The set of valid states is visible
in one place. The set of valid transitions is visible in the method signatures
and their guards. The transition method raises an error the moment code
attempts an invalid transition. A consumer downstream never has to detect the
impossible state sequence.

---

## Applying the Pattern

### Step 1: Define a closed set of states

Use `String(choices=...)` to restrict the status field to a known set of
values. Protean rejects any value not in the list at the field level.

```python
--8<-- "patterns/aggregate-state-machines/001.py:states"
```

Using an enum makes the valid states discoverable, importable, and usable
in tests and consumers.

### Step 2: Build the aggregate with guarded transition methods

Each lifecycle transition is a named method. The method validates the
current state, performs the transition, and raises a domain event.

```python
--8<-- "patterns/aggregate-state-machines/001.py:aggregate"
```

!!! note "Guard placement"
    Each transition method checks its precondition with an early `if` guard in
    its own body. This is the simplest and most readable approach. Protean's
    `@invariant.pre` decorator is an alternative that runs before every
    mutation. It catches violations that a method guard misses, but it is less
    precise for per-method guards.

### Step 3: Keep handlers thin

With the state machine inside the aggregate, handlers become orchestrators:

```python
--8<-- "patterns/aggregate-state-machines/001.py:handlers"
```

Every handler follows the same three-line pattern: load, call, save. The
aggregate guards its own transitions.

### Step 4: Test the state machine directly

Because the aggregate holds the lifecycle rules, you can test them with plain
calls and no infrastructure:

```python
--8<-- "patterns/aggregate-state-machines/001.py:tests"
```

Each test verifies a specific transition rule. The state machine's behavior
is fully documented by the test names.

---

### Visualizing the state machine

For complex lifecycles, a transition map shows every state and its allowed
transitions in one place:

```python
--8<-- "patterns/aggregate-state-machines/002.py:transition_map"
```

!!! tip "Use the `Status` field for automatic enforcement"
    Protean's `Status` field can enforce transitions automatically, no manual
    guards required. The `Status` field uses a simpler format (`state →
    [allowed_targets]`) rather than the method-mapped dict above. See the
    [Status Transitions](../guides/domain-behavior/status-transitions.md) guide
    for details.

!!! note "Idempotent transitions"
    Some operations should be safe to call twice, e.g., `cancel()` on an
    already-cancelled order. With `Status` field transitions, add the state to its
    own target list (`OrderStatus.CANCELLED: [OrderStatus.CANCELLED]`). Without `Status` transitions, add an explicit early
    return in the method guard.

---

### Using `@invariant.pre` and `@invariant.post` as safety nets

For a second check on top of the method guards, add invariants that run on
every mutation. These invariants catch any invalid change that a method guard
misses:

```python
--8<-- "patterns/aggregate-state-machines/003.py:invariants"
```

The pre-invariant blocks any change to an order in a terminal state. The
post-invariants check that a shipped order has a tracking number and a
`shipped_at` time. Add a post-invariant like these for each state that needs
its own data.

!!! note "Pre vs post invariants for state machines"
    `@invariant.pre` runs **before** state changes and is ideal for
    blocking invalid transitions. `@invariant.post` runs **after** state
    changes and is better for validating that the resulting state is
    consistent (e.g., "a shipped order must have a tracking number").
    Use both together for comprehensive protection.

---

## Anti-Patterns

### Bare string assignments without guards

```python
# fragment
# Anti-pattern: no guard, any transition is allowed
def ship(self, tracking_number: str) -> None:
    self.status = "shipped"  # Works even if status is "cancelled"
    self.tracking_number = tracking_number
```

Without a guard, the method silently permits impossible transitions.

**To fix it**, add a guard at the top of every transition method:

```python
# fragment
def ship(self, tracking_number: str) -> None:
    if self.status != OrderStatus.PAID.value:
        raise ValidationError(
            {"status": [f"Cannot ship an order in '{self.status}' status"]}
        )
    self.status = OrderStatus.SHIPPED.value
    self.tracking_number = tracking_number
```

### Open-ended status field

```python
# fragment
# Anti-pattern: status accepts any string
@domain.aggregate
class Order:
    status = String(default="draft")  # No choices constraint
```

Without `choices`, the field accepts `"shiped"` (typo), `"DRAFT"` (wrong
case), or `"pending_review"` (invented state). Use an enum:

```python
--8<-- "patterns/aggregate-state-machines/001.py:status_field"
```

### Generic `update_status` method

```python
# fragment
# Anti-pattern: one method for all transitions
def update_status(self, new_status: str) -> None:
    self.status = new_status
```

The `update_status` method is a plain setter under another name. It has no
guards, raises no events, and loses the ubiquitous language. "Ship an order"
becomes `order.update_status("shipped")` instead of `order.ship()`.

Each transition has different preconditions, different side effects, and
different events. They deserve separate methods.

### Transition logic in handlers

```python
# fragment
# Anti-pattern: handler knows the state machine
@handle(ShipOrder)
def ship_order(self, command: ShipOrder):
    repo = current_domain.repository_for(Order)
    order = repo.get(command.order_id)

    if order.status != "paid":
        raise ValidationError({"status": ["Only paid orders can be shipped"]})

    order.status = "shipped"
    order.tracking_number = command.tracking_number
    order.shipped_at = datetime.now(timezone.utc)

    order.raise_(OrderShipped(
        order_id=order.order_id,
        tracking_number=command.tracking_number,
    ))

    repo.add(order)
```

The handler knows which states are valid, performs the transition, and
raises the event. If another handler, event handler, or batch job also
needs to ship orders, the logic is duplicated. Move the state machine
into the aggregate.

### Status checks scattered across consumers

```python
# fragment
# Anti-pattern: consumers guard against impossible states
@handle(OrderShipped)
def on_order_shipped(self, event: OrderShipped):
    order = repo.get(event.order_id)

    # Defensive check because the aggregate doesn't guard transitions
    if order.status == "cancelled":
        logger.warning("Shipped event for cancelled order %s", event.order_id)
        return

    # ... process shipment
```

If consumers need to guard against impossible state sequences, the aggregate is
failing to enforce its own transitions. When the aggregate enforces its own
state machine, consumers can trust the events they receive.

---

## Summary

| Aspect | Without State Machine | With State Machine |
|--------|----------------------|-------------------|
| Valid states | Implicit, scattered in code | Explicit enum with `choices` |
| Valid transitions | Discovered by reading all handlers | Visible in method signatures and guards |
| Invalid transitions | Silent, accepted | Immediate `ValidationError` |
| Transition logic | Duplicated across handlers | Centralized in aggregate methods |
| Events | Manually raised in handlers | Raised inside transition methods |
| New developer onboarding | Read every handler to understand lifecycle | Read the aggregate class |
| Testing | Requires handlers + infrastructure | Direct method calls on aggregate |
| Adding a new state | Touch every handler that checks status | Add enum value + one method |

An aggregate with a `status` field is a state machine. Make it an explicit one.
Define the states as an enum. Define each transition as a named method with a
guard. Raise events from the transition. Let the aggregate enforce its own
lifecycle.

---

!!! tip "Related reading"
    **Patterns:**

    - [Encapsulate State Changes](encapsulate-state-changes.md): Named methods for every state transition.
    - [Validation Layering](validation-layering.md): Different validation at different layers.

    **Guides:**

    - [Invariants](../guides/domain-behavior/invariants.md): Pre and post invariants on aggregates.
    - [Aggregate Mutation](../guides/domain-behavior/aggregate-mutation.md): Named methods and state changes.
