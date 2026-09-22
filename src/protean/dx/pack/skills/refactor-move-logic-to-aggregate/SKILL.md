---
name: refactor-move-logic-to-aggregate
description: >
  Move business logic from handlers, services, or endpoints into aggregate methods where it belongs.
  Detects "logic leak" — validation, calculations, state transitions, and business rules scattered
  outside the domain model — and refactors them into rich aggregate methods with proper invariants.
  Use when the user says "move logic to aggregate", "handler is too fat", "fix logic leak",
  "enrich my aggregate", "make aggregate rich", "handler has too much logic", "anemic domain model",
  or when an audit identifies logic leaks or anemic aggregates.
license: Apache-2.0
compatibility: "Requires Python 3.11+, protean framework"
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [aggregate, command-handler, event-handler]
---

# Refactor: Move Logic to Aggregate

> **Illustrative, guided refactoring.** This is a before→after walkthrough, not an
> automated transform: recognize the smell and apply the change yourself, adapting to the
> code at hand. The `move_logic_*_before.py` asset is the intentional starting point
> (anemic aggregate / fat handler); the `*_after.py` asset shows the rich-aggregate target.

Identify business logic that has leaked out of aggregates into handlers, services, or endpoints,
and move it back into rich aggregate methods with proper invariants and events.

## What this produces

| Output | Purpose |
|--------|---------|
| **Rich aggregate methods** | Business logic encapsulated in the aggregate |
| **Aggregate invariants** | Validation rules as `@invariant.post` decorators |
| **Thin handlers** | Handlers reduced to load → call → persist |
| **Updated tests** | Tests for aggregate behavior, not handler internals |

## Detection patterns

### The "controller handler"

Handler does validation, calculation, construction, and persistence:

```python
# RED FLAG: handler has 10+ lines of logic
@handle(PlaceOrder)
def place_order(self, command):
    if not command.items:                    # Validation
        raise ValidationError(...)
    total = sum(i.price * i.qty ...)         # Calculation
    if total > MAX:                          # Business rule
        raise ValidationError(...)
    order = Order(total=total, status="PLACED")  # Construction
    domain.repository_for(Order).add(order)
```

### The "anemic aggregate"

Aggregate is a data bag — no methods, no invariants:

```python
# RED FLAG: only fields, no behavior
@domain.aggregate
class Order:
    customer_id = String(required=True)
    total = Float(default=0.0)
    status = String(default="DRAFT")
    # No methods!
```

### Specific signals

| Signal | Where found | What to move |
|--------|------------|-------------|
| `if` + `raise ValidationError` | Handler | `@invariant.post` on aggregate |
| Arithmetic / calculations | Handler | Aggregate method |
| `self.status = "..."` | Handler setting aggregate fields | Aggregate state-transition method |
| Multiple attribute assignments | Handler building aggregate state | Aggregate factory or method |
| `if status != "X": raise` | Handler guard clause | Aggregate method pre-condition |

## Process

### Step 1: Identify the logic to move

Read the handler and categorize each line:

| Line | Category | Destination |
|------|----------|-------------|
| `if not command.items: raise` | Validation | Aggregate invariant or method guard |
| `total = sum(...)` | Calculation | Aggregate method |
| `if total > MAX: raise` | Business rule | Aggregate invariant |
| `order.status = "PLACED"` | State transition | Aggregate method |
| `repo.add(order)` | Persistence | Stays in handler |
| `order = Order(...)` | Construction | Stays in handler (or factory) |

### Step 2: Create aggregate methods

For each group of logic, create an aggregate method:

```python
@domain.aggregate
class Order:
    customer_id = String(required=True)
    items = HasMany(LineItem)
    total = ValueObject(Money)
    status = String(default="DRAFT")

    def place(self, items: list[dict]) -> None:
        """Place the order with the given items."""
        for item_data in items:
            self.add_items(LineItem(**item_data))
        self.total = self._calculate_total()
        self.status = "PLACED"
        self.raise_(OrderPlaced(order_id=self.id, total=self.total.amount))

    def _calculate_total(self) -> Money:
        """Sum all line item totals."""
        total = 0.0
        for item in self.items:
            total += item.unit_price.amount * item.quantity
        return Money(amount=total)
```

### Step 3: Add invariants

Move validation from handlers into `@invariant.post`:

```python
    @invariant.post
    def must_have_items_when_placed(self):
        """A placed order must have at least one item."""
        if self.status == "PLACED" and not self.items:
            raise ValidationError({"items": ["Placed order must have items"]})

    @invariant.post
    def total_must_not_exceed_maximum(self):
        """Order total cannot exceed $50,000."""
        if self.total and self.total.amount > 50000:
            raise ValidationError({"total": ["Exceeds maximum order amount"]})
```

### Step 4: Slim down the handler

The handler becomes load → call → persist:

```python
@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order(customer_id=command.customer_id)
        order.place(items=command.items)
        domain.repository_for(Order).add(order)
```

**The ideal handler is 3-5 lines**: load/create aggregate, call one method, persist.

### Step 5: Move tests to aggregate level

```python
# Before: testing handler internals
def test_place_order_validates_items():
    with pytest.raises(ValidationError):
        handler.place_order(PlaceOrder(items=[]))

# After: testing aggregate behavior
def test_order_must_have_items_when_placed():
    order = Order(customer_id="CUST-001")
    with pytest.raises(ValidationError):
        order.place(items=[])  # Invariant fires
```

## Common mistakes

1. **Moving persistence into the aggregate** — `repository.add()` stays in the handler.
   Aggregates don't know about persistence.

2. **Creating a method per field** — If the handler sets 3 fields, create ONE method
   that captures the business operation, not 3 setter methods.

3. **Leaving events in the handler** — `raise_()` belongs inside the aggregate method,
   not in the handler after calling the method.

4. **Over-guarding** — Not every `if` is an invariant. Simple null checks in handlers
   (`if not command.customer_id`) are often handled by field `required=True`.

5. **Forgetting to update tests** — After moving logic, tests should assert aggregate
   behavior directly, not go through `domain.process()` for unit tests.

## Quick example

```python
# BEFORE: fat handler, anemic aggregate
@handle(CloseTicket)
def close_ticket(self, command):
    ticket = domain.repository_for(Ticket).get(command.ticket_id)
    if ticket.status == "CLOSED":
        raise ValidationError("Already closed")
    if ticket.status == "OPEN":
        raise ValidationError("Must be assigned first")
    ticket.status = "CLOSED"
    ticket.closed_at = datetime.now(UTC)
    ticket.resolution = command.resolution
    domain.repository_for(Ticket).add(ticket)

# AFTER: thin handler, rich aggregate
@handle(CloseTicket)
def close_ticket(self, command):
    ticket = domain.repository_for(Ticket).get(command.ticket_id)
    ticket.close(resolution=command.resolution)
    domain.repository_for(Ticket).add(ticket)
```

## Examples

- Ticket: [before](assets/move_logic_ticket_before.py) and [after](assets/move_logic_ticket_after.py)

## Detailed references

- [Identifying logic leaks](references/identifying-logic-leaks.md) — Heuristics and examples
- [Anti-patterns](references/anti-patterns.md) — Common refactoring mistakes

## Related skills

- [aggregate](../aggregate/SKILL.md) — Aggregate patterns
- [command-handler](../command-handler/SKILL.md) — Handler patterns
- [audit-domain](../audit-domain/SKILL.md) — Detects logic leaks

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
