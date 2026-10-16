# Thin Handlers, Rich Domain

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

This is the **anemic domain model**. An anti-pattern where domain objects carry
data but no behavior, and business logic lives in service layers (handlers,
application services, utility functions).

The consequences:

- **Logic duplication**: Another handler that processes admin overrides
  reimplements the refund calculation. A batch job that auto-refunds expired
  subscriptions has its own version. Each diverges slightly over time.

- **Untestable business logic**: To test refund eligibility, you need to
  construct a command, set up a repository, create a handler instance, and run
  it within a UoW. The business rule is buried inside infrastructure.

- **Hidden dependencies**: The handler knows about refund windows, partial
  refunds, shipment interception, and warehouse notifications. These are
  domain concerns scattered across infrastructure code.

- **Aggregate bypass**: Since the aggregate has no methods, nothing prevents
  other code from setting `order.status = "refund_requested"` without
  checking eligibility or raising events.

The root cause: **behavior is in the wrong place**. The handler should
orchestrate; the domain model should think.

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

### Before: Thick Handler

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

### After: Thin Handler, Rich Aggregate

```python
--8<-- "patterns/thin-handlers-rich-domain/refunds/domain.py:aggregate"
--8<-- "patterns/thin-handlers-rich-domain/refunds/domain.py:handler"
```

The handler is 5 lines. The aggregate has the business logic organized into
clear, named methods with specific responsibilities.

---

## Where Logic Lives

### Aggregate Methods: Single-Aggregate Business Rules

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

### Domain Services: Cross-Aggregate Coordination

Logic that reads from multiple aggregates but modifies only one belongs in a
domain service:

```python
--8<-- "patterns/thin-handlers-rich-domain/002.py:transfer"
--8<-- "patterns/thin-handlers-rich-domain/002.py:handler"
```

The handler loads both aggregates and calls the domain service. The domain
service coordinates the validation logic. The aggregate's `debit()` method
handles the actual state change. Each component has a clear responsibility.

### Value Objects: Concept-Level Logic

Logic intrinsic to a domain concept belongs in the value object:

```python
--8<-- "patterns/thin-handlers-rich-domain/003.py:money"
```

Currency-matching logic lives in `Money`, not in the handler that adds two
monetary amounts.

---

## The Three-Line Handler Test

If your handler has more than the three canonical lines (load, call, save),
ask whether the extra logic belongs in the domain model:

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

The handler is the **coordinator**, not the **decision-maker**.

---

## Signs Your Handler Is Too Thick

1. **If-else business logic**: Conditional branching based on aggregate state
   should be inside the aggregate.

2. **Calculations**: Computing amounts, percentages, dates, or derived values
   belongs in the aggregate or a domain service.

3. **Multiple aggregate method calls**: If the handler calls several methods
   in sequence on the same aggregate, those methods should be composed into a
   single higher-level method on the aggregate.

4. **Event raising**: Events should be raised inside aggregate methods, not
   in the handler.

5. **Domain knowledge**: If the handler "knows" business rules (refund windows,
   discount calculations, eligibility criteria), that knowledge belongs in the
   domain model.

6. **More than 10 lines of non-infrastructure code**: A handler that's longer
   than load-call-save is a code smell.

---

## Testing Benefits

The most compelling reason for thin handlers: **domain logic becomes directly
testable**.

### Testing with Thick Handlers (Hard)

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

### Testing with Thin Handlers (Easy)

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

The reservation logic (checking availability, preventing double-reservation,
updating quantities) lives in `Inventory.reserve()`, not in the handler.
`OrderPlaced` belongs to `Order`, so `stream_category` points the handler at the
order stream. Without it the handler would listen to the inventory stream and
never see the event.

---

## Application Services Follow the Same Pattern

Application services orchestrate use cases and should also be thin:

```python
--8<-- "patterns/thin-handlers-rich-domain/005.py:application_service"
```

Load or create, call domain methods, save. The application service coordinates
the sequence; the domain model contains the logic.

---

## When the Handler Has Extra Lines

Some legitimate additions to the three-line pattern:

### Loading Additional Data for Domain Services

```python
--8<-- "patterns/thin-handlers-rich-domain/002.py:handler"
```

Loading a second aggregate for a domain service is fine. The handler is still
just orchestrating.

### Creating New Aggregates

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

Construction with multiple `add_item` calls is orchestration, not logic.

### Layer 4 Guards

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
    - [Aggregate Mutation](../guides/domain-behavior/aggregate-mutation.md): Pushing state changes into aggregates.
