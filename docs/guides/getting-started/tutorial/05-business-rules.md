# Chapter 5: Business Rules and Invariants

A domain model without business rules is just a data container. In this
chapter we add **invariants** — rules that keep our aggregates in a valid
state — and encapsulate behavior in **aggregate methods**.

## Field-Level Validation

We have already seen some validation through field options:

- `required=True` — the field must be present
- `choices=OrderStatus` — the value must be one of the enum members
- `max_length=150` — the string cannot exceed this length

When validation fails, Protean raises a `ValidationError`:

```python
>>> Order(customer_name="", status="INVALID")
ValidationError: {
    'customer_name': ['is required'],
    'status': ["Value 'INVALID' is not a valid choice. ..."]
}
```

Field validation catches simple data errors at the boundary. But some
rules involve multiple fields or depend on the aggregate's state. That
is where invariants come in.

## Post-Invariants: Validating State

A **post-invariant** is checked *after every state change* — on creation
and on every subsequent mutation. Use `@invariant.post`:

```python
{! docs_src/guides/getting-started/tutorial/ch05.py [ln:27-72] !}
```

The `order_must_have_items` invariant runs whenever the Order is created
or modified. If the items list is empty, it rejects the change:

```python
>>> Order(customer_name="Alice")
ValidationError: {'_entity': ['An order must contain at least one item']}
```

!!! info "When Post-Invariants Run"
    Post-invariants run after initialization and after every attribute
    change. They guarantee that the aggregate is *always* in a valid state.
    If a mutation violates an invariant, the change is rejected and the
    aggregate stays in its previous state.

## Pre-Invariants: Guarding Transitions

A **pre-invariant** is checked *before* state changes are applied. Use
it to prevent invalid operations:

```python
@invariant.pre
def cannot_modify_shipped_order(self):
    if self.status == OrderStatus.SHIPPED.value:
        raise ValidationError(
            {"_entity": ["Cannot modify an order that has been shipped"]}
        )
```

This prevents any modifications once an order has been shipped:

```python
>>> order.ship()
>>> order.add_item("Sapiens", 1, Money(amount=18.99))
ValidationError: {'_entity': ['Cannot modify an order that has been shipped']}
```

### Pre vs Post: When to Use Which

| Use Pre-Invariants When... | Use Post-Invariants When... |
|---------------------------|---------------------------|
| Guarding state transitions | Validating the resulting state |
| Preventing invalid operations | Ensuring multi-field consistency |
| Checking "can this happen?" | Checking "is this state valid?" |

## Aggregate Methods

Rather than mutating aggregate fields directly, encapsulate behavior in
methods:

```python
def add_item(self, book_title: str, quantity: int, unit_price: Money):
    """Add an item to this order."""
    self.add_items(
        OrderItem(
            book_title=book_title,
            quantity=quantity,
            unit_price=unit_price,
        )
    )

def confirm(self):
    """Confirm the order for processing."""
    self.status = OrderStatus.CONFIRMED.value

def ship(self):
    """Mark the order as shipped."""
    self.status = OrderStatus.SHIPPED.value
```

Methods become the **public API** of your aggregate. External code calls
`order.confirm()` rather than `order.status = "CONFIRMED"`. This keeps
business logic inside the aggregate where invariants can enforce it.

## Atomic Changes

Sometimes you need to make multiple changes that would individually
violate invariants but result in a valid state. Use `atomic_change` to
temporarily defer invariant checks:

```python
from protean import atomic_change

with atomic_change(order) as order:
    order.status = "PROCESSING"  # Intermediate state
    order.customer_name = "Updated Name"
    # Invariants are deferred until the block exits
# Invariants checked here — if final state is valid, it passes
```

Inside the `atomic_change` block, invariants are suspended. They run
when the block exits — if the final state is invalid, the error is
raised then.

## Error Handling Patterns

`ValidationError` carries a dictionary of error messages:

```python
from protean.exceptions import ValidationError

try:
    Order(customer_name="")
except ValidationError as e:
    print(e.messages)
    # {'customer_name': ['is required'],
    #  '_entity': ['An order must contain at least one item']}
```

- **Field-level errors** are keyed by field name: `{'customer_name': [...]}`
- **Entity-level errors** use the `_entity` key: `{'_entity': [...]}`
- **Service-level errors** use `_service` (seen in Chapter 10)

This structure makes it straightforward to present errors in a UI — map
field errors to form inputs, and entity errors to a general message area.

## Putting It Together

```python
{! docs_src/guides/getting-started/tutorial/ch05.py [ln:89-133] !}
```

Run it:

```shell
$ python bookshelf.py
=== Field Validation ===
Caught: {'customer_name': ['is required']}
Caught: {'status': ["Value 'INVALID_STATUS' is not a valid choice. ..."]}

=== Post-Invariant: Must Have Items ===
Caught: {'_entity': ['An order must contain at least one item']}

=== Aggregate Methods ===
Order: Alice, 2 items
Status: PENDING
After confirm: CONFIRMED
After ship: SHIPPED

=== Pre-Invariant: Cannot Modify Shipped ===
Caught: {'_entity': ['Cannot modify an order that has been shipped']}

All checks passed!
```

## Full Source

```python
{! docs_src/guides/getting-started/tutorial/ch05.py !}
```

## Summary

In this chapter you learned:

- **Field validation** (`required`, `choices`, `max_length`) catches
  basic data errors at creation time.
- **Post-invariants** (`@invariant.post`) validate state after every
  change, keeping the aggregate always consistent.
- **Pre-invariants** (`@invariant.pre`) guard state transitions,
  preventing invalid operations.
- **Aggregate methods** encapsulate business logic and serve as the
  public API for state changes.
- **`atomic_change`** lets you make multi-step changes without triggering
  intermediate invariant checks.

We now have a rich domain model with aggregates, entities, value objects,
and business rules. In the next part, we will add **commands** and
**events** — the building blocks of an event-driven architecture.

## Next

[Chapter 6: Commands and Command Handlers →](06-commands.md)
