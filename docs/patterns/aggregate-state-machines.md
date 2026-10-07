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
  What about `"PAID"` or `"Shipped"`? The set of allowed states lives only
  in the developer's head and whatever strings happen to appear in handler
  code.

- **Transitions are invisible**: Which states can transition to which? Can a
  `"delivered"` order be cancelled? The only way to answer is to read every
  handler, every event handler, and every batch job that touches the
  `status` field.

- **Invalid transitions are silent**: Setting `order.status = "shipped"`
  when the order is in `"draft"` produces no error, no log, no event. The
  aggregate happily accepts any string, and downstream consumers see
  nonsensical state sequences.

- **New team members guess**: A developer who joined last month adds a new
  handler that sets `status = "processing"`, a state that no consumer knows
  about. Nothing in the codebase prevents it.

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

The aggregate becomes its own state machine. The set of valid states is
visible in one place. The set of valid transitions is visible in the
method signatures and their guards. Invalid transitions are caught at the
moment they are attempted, not downstream when a consumer sees an
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
    The precondition check lives directly inside each transition method as
    an early `if` guard. This is the simplest and most readable approach.
    Protean's `@invariant.pre` decorator is an alternative that runs
    before every mutation, useful as a safety net but less precise for
    per-method guards.

### Step 3: Keep handlers thin

With the state machine inside the aggregate, handlers become orchestrators:

```python
--8<-- "patterns/aggregate-state-machines/001.py:handlers"
```

Every handler follows the same three-line pattern: load, call, save. The
aggregate guards its own transitions.

### Step 4: Test the state machine directly

Because the lifecycle rules live in the aggregate, tests are simple and
infrastructure-free:

```python
--8<-- "patterns/aggregate-state-machines/001.py:tests"
```

Each test verifies a specific transition rule. The state machine's behavior
is fully documented by the test names.

---

### Visualizing the state machine

For complex lifecycles, a transition map makes the state machine scannable
at a glance:

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

For aggregates where you want a belt-and-suspenders approach, add
invariants that run on every mutation to catch anything that slips through:

```python
--8<-- "patterns/aggregate-state-machines/003.py:invariants"
```

The pre-invariant prevents invalid transitions on terminal states. The
post-invariants ensure that every state has the data it requires. Together
they make impossible states truly impossible.

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

**Fix:** Add a guard at the top of every transition method:

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
# Correct: constrained to known states
--8<-- "patterns/aggregate-state-machines/001.py:status_field"
```

### Generic `update_status` method

```python
# fragment
# Anti-pattern: one method for all transitions
def update_status(self, new_status: str) -> None:
    self.status = new_status
```

This is a setter with extra steps. It has no guards, raises no events, and
loses the ubiquitous language. "Ship an order" becomes
`order.update_status("shipped")` instead of `order.ship()`.

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

If consumers need to guard against impossible state sequences, the
aggregate is not doing its job. When the aggregate enforces its own state
machine, consumers can trust the events they receive.

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
