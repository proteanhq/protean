# Keep handlers thin and the domain rich

## The Problem

A developer writes a command handler for processing refunds:

```python
# fragment
@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):

    @handle(RequestRefund)
    def request_refund(self, command: RequestRefund):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Check if the order is eligible for refund
        if order.status not in ("shipped", "delivered"):
            raise ValidationError(
                {"status": ["Only shipped or delivered orders can be refunded"]}
            )

        # Check if the refund window has passed
        if order.delivered_at:
            days_since_delivery = (datetime.now(timezone.utc) - order.delivered_at).days
            if days_since_delivery > 30:
                raise ValidationError(
                    {"timing": ["Refund window has expired (30 days)"]}
                )

        # Calculate the refund amount
        refund_amount = order.total
        if order.partial_refund_amount:
            refund_amount = order.total - order.partial_refund_amount

        if command.amount and command.amount < refund_amount:
            refund_amount = command.amount

        # Apply the refund
        order.status = "refund_requested"
        order.refund_amount = refund_amount
        order.refund_requested_at = datetime.now(timezone.utc)
        order.refund_reason = command.reason

        # Raise events
        order.raise_(RefundRequested(
            order_id=order.order_id,
            customer_id=order.customer_id,
            amount=refund_amount,
            reason=command.reason,
        ))

        # Check if we need to notify the warehouse
        if order.status == "shipped" and not order.delivered_at:
            order.raise_(ShipmentInterceptRequested(
                order_id=order.order_id,
                tracking_number=order.tracking_number,
            ))

        repo.add(order)
```

This handler is 40 lines of business logic. It validates, calculates, mutates,
decides, and raises events. The `Order` aggregate is a passive data container
that the handler manipulates.

This is the **anemic domain model**. In this anti-pattern, domain objects carry
data but no behavior. Service layers (handlers, application services, utility
functions) contain the business logic.

The consequences:

- **Handlers duplicate the logic**: A second handler, for admin overrides,
  reimplements the refund calculation. A batch job auto-refunds expired
  subscriptions with its own version of the calculation. Each diverges slightly
  over time.

- **You cannot test the business logic on its own**: To test refund
  eligibility, you need to construct a command, set up a repository, create a
  handler instance, and run it within a UoW. The handler mixes the business
  rule with infrastructure code.

- **The handler hides domain dependencies**: The handler knows about refund
  windows, partial refunds, shipment interception, and warehouse notifications.
  These are domain concerns scattered across infrastructure code.

- **Other code can bypass the aggregate**: Since the aggregate has no methods,
  nothing prevents other code from setting `order.status = "refund_requested"`
  without checking eligibility or raising events.

The root cause: **behavior is in the wrong place**. The handler should load,
call and save. The domain model should make the business decisions.

---

## The Pattern

Keep handlers **thin**. They load, delegate, and save. Move all business logic
into **aggregates** and **domain services**.

```
Thin handler:
  1. Load aggregate from repository
  2. Call one aggregate method
  3. Save aggregate to repository

Rich domain:
  - Aggregate methods validate, mutate, and raise events
  - Domain services coordinate cross-aggregate logic
  - Value objects encapsulate concept rules
```

The handler pattern is almost always three lines:

```python
# fragment
@handle(SomeCommand)
def handle_command(self, command: SomeCommand):
    repo = current_domain.repository_for(Aggregate)
    aggregate = repo.get(command.aggregate_id)
    aggregate.do_the_thing(command.relevant_data)
    repo.add(aggregate)
```

Load. Call. Save. Everything else belongs in the domain model.

---

## Applying the Pattern

### Before: the handler contains the business logic

```python
# fragment
@handle(RequestRefund)
def request_refund(self, command: RequestRefund):
    repo = current_domain.repository_for(Order)
    order = repo.get(command.order_id)

    # 40 lines of business logic in the handler
    if order.status not in ("shipped", "delivered"):
        raise ValidationError(...)

    days_since = (datetime.now(timezone.utc) - order.delivered_at).days
    if days_since > 30:
        raise ValidationError(...)

    refund_amount = order.total - (order.partial_refund_amount or 0)
    if command.amount and command.amount < refund_amount:
        refund_amount = command.amount

    order.status = "refund_requested"
    order.refund_amount = refund_amount
    order.refund_requested_at = datetime.now(timezone.utc)
    order.refund_reason = command.reason

    order.raise_(RefundRequested(...))

    if order.status == "shipped" and not order.delivered_at:
        order.raise_(ShipmentInterceptRequested(...))

    repo.add(order)
```

### After: the aggregate contains the business logic

```python
--8<-- "patterns/thin-handlers-rich-domain/refunds/domain.py:aggregate"
--8<-- "patterns/thin-handlers-rich-domain/refunds/domain.py:handler"
```

The handler is 5 lines. The aggregate has the business logic organized into
clear, named methods with specific responsibilities.

---

## Which domain element should contain the logic?

### Put single-aggregate business rules in aggregate methods

Logic that depends only on the aggregate's own state belongs in aggregate
methods:

```python
--8<-- "patterns/thin-handlers-rich-domain/001.py:account"
```

All withdrawal logic (status check, daily limits, balance check, total
tracking) is in the aggregate. The handler is:

```python
--8<-- "patterns/thin-handlers-rich-domain/001.py:handler"
```

### Put cross-aggregate coordination in domain services

Logic that reads from multiple aggregates but modifies only one belongs in a
domain service:

```python
--8<-- "patterns/thin-handlers-rich-domain/002.py:transfer"
--8<-- "patterns/thin-handlers-rich-domain/002.py:handler"
```

The handler loads both aggregates and calls the domain service. The domain
service runs the validation across both aggregates. The aggregate's `debit()`
method makes the actual state change. Each component has a clear
responsibility.

### Put concept-level logic in value objects

Logic intrinsic to a domain concept belongs in the value object:

```python
--8<-- "patterns/thin-handlers-rich-domain/003.py:money"
```

`Money` checks that two amounts share a currency. The handler that adds two
monetary amounts does not check the currency itself.

---

## Test whether your handler needs more than three lines

Your handler may have more than the three canonical lines (load, call, save).
In that case, ask whether the extra logic belongs in the domain model:

| Handler Line | Belongs In Handler? | Move To |
|-------------|--------------------|----|
| `repo.get(id)` | Yes | —  |
| `aggregate.method(data)` | Yes | —  |
| `repo.add(aggregate)` | Yes | —  |
| `if aggregate.status != "active"` | No | Aggregate method (precondition) |
| `amount = command.total * 0.9` | No | Aggregate method (calculation) |
| `aggregate.raise_(Event(...))` | No | Aggregate method (event raising) |
| `if user.role != "admin"` | Maybe | Handler (Layer 4 contextual check) |
| `service.validate(a, b)` | Yes | Domain service (cross-aggregate) |

The handler sequences the calls. The domain model makes the business decisions.

---

## How can you tell your handler is too thick?

1. **The handler branches on business rules**: Put conditional branching based
   on aggregate state inside the aggregate.

2. **The handler calculates values**: Compute amounts, percentages, dates, or
   derived values in the aggregate or a domain service.

3. **The handler calls several aggregate methods**: If the handler calls
   several methods in sequence on the same aggregate, compose those methods
   into a single higher-level method on the aggregate.

4. **The handler raises events**: Raise events inside aggregate methods only.

5. **The handler checks business rules**: If the handler checks business rules
   (refund windows, discount calculations, eligibility criteria), move those
   rules into the domain model.

6. **The handler has more than 10 lines of non-infrastructure code**: A handler
   that's longer than load-call-save is a code smell.

---

## How do thin handlers make testing easier?

The main reason for thin handlers: **you can test domain logic directly**.

### Test through thick handlers (hard)

```python
# fragment
class TestRefund:

    def test_refund_eligibility(self, test_domain):
        # Must set up: command, handler, repository, UoW
        test_domain.register(Order)
        test_domain.register(OrderCommandHandler)
        test_domain.init(traverse=False)

        with test_domain.domain_context():
            # Create and persist an order
            repo = test_domain.repository_for(Order)
            order = Order(status="delivered", total=100.0, delivered_at=datetime.now())
            repo.add(order)

            # Build command
            command = RequestRefund(order_id=order.order_id, reason="Changed mind")

            # Process through handler
            test_domain.process(command)

            # Verify
            updated = repo.get(order.order_id)
            assert updated.status == "refund_requested"
```

### Test with thin handlers (easy)

The `test_domain` fixture comes from a `conftest.py` next to the tests. It
initializes the domain and opens a domain context, so the aggregate can raise
events:

```python
# fragment
--8<-- "patterns/thin-handlers-rich-domain/conftest.py:fixture"
```

Each test builds an order and calls its method:

```python
# fragment
--8<-- "patterns/thin-handlers-rich-domain/test_refund.py:tests"
```

Five focused tests, each testing a specific business rule, without any
infrastructure setup. Fast, readable, and comprehensive.

---

## Event Handlers Follow the Same Pattern

Event handlers should be equally thin:

```python
--8<-- "patterns/thin-handlers-rich-domain/004.py:event_handler"
```

`Inventory.reserve()` contains the reservation logic (checking availability,
preventing double-reservation, updating quantities). The handler only calls it.
`OrderPlaced` belongs to `Order`, so `stream_category` points the handler at
the order stream. Without it the handler would listen to the inventory stream
and never see the event.

---

## Application Services Follow the Same Pattern

Application services orchestrate use cases and should also be thin:

```python
--8<-- "patterns/thin-handlers-rich-domain/005.py:application_service"
```

Load or create, call domain methods, save. The application service runs the
steps in order. The domain model contains the business logic.

---

## When the Handler Has Extra Lines

Some legitimate additions to the three-line pattern:

### Load additional data for domain services

```python
--8<-- "patterns/thin-handlers-rich-domain/002.py:handler"
```

The handler can load a second aggregate for a domain service. The handler is
still just orchestrating.

### Create new aggregates

```python
# fragment
@handle(PlaceOrder)
def place_order(self, command: PlaceOrder):
    order = Order(
        order_id=command.order_id,
        customer_id=command.customer_id,
    )
    for item in command.items:
        order.add_item(**item)  # Aggregate method
    order.place()               # Aggregate method
    repo.add(order)
```

The handler builds the order with multiple `add_item` calls. That code
orchestrates aggregate methods and contains no business logic.

### Apply Layer 4 guards in the handler

```python
# fragment
@handle(CancelOrder)
def cancel_order(self, command: CancelOrder):
    order = repo.get(command.order_id)

    # Contextual guard (Layer 4)
    if command.requested_by_role not in ("admin", "customer"):
        raise AuthorizationError("Unauthorized")

    order.cancel(command.reason)
    repo.add(order)
```

Authorization checks are the handler's responsibility (see
[Validation Layering](validation-layering.md)).

---

## Summary

| Aspect | Thick Handlers | Thin Handlers + Rich Domain |
|--------|---------------|----------------------------|
| Business logic | Scattered in handlers | Centralized in aggregates |
| Handler size | 20-50+ lines | 3-5 lines |
| Duplication | High (multiple handlers, same rules) | None (single aggregate method) |
| Testability | Requires infrastructure | Direct method calls |
| Aggregate role | Data container | Behavior + data |
| Domain service role | Unused | Cross-aggregate coordination |
| Code organization | Logic by handler | Logic by domain concept |
| Readability | Must read handler to understand rules | Method names express intent |

Handlers orchestrate. Aggregates think. Load, call, save. If your handler knows
business rules, the rules are in the wrong place.

---

!!! tip "Related reading"
    **Concepts:**

    - [Command Handlers](../concepts/building-blocks/command-handlers.md): Command handler responsibilities.
    - [Application Services](../concepts/building-blocks/application-services.md): Orchestrating use cases.
    - [Domain Services](../concepts/building-blocks/domain-services.md): Cross-aggregate business logic.

    **Guides:**

    - [Command Handlers](../guides/change-state/command-handlers.md): Defining and implementing command handlers.
    - [Application Services](../guides/change-state/application-services.md): The @use_case decorator and service workflow.
    - [Aggregate Mutation](../guides/domain-behavior/aggregate-mutation.md):
      Writing state changes as aggregate methods.
