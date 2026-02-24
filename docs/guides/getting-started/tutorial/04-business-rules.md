# Chapter 4: Business Rules and Invariants

In this chapter we will add invariants to our Order aggregate so that
orders cannot be empty, and shipped orders cannot be modified.

## Post-Invariants: Validating State

Let's add a rule: every order must have at least one item. A
**post-invariant** is checked *after every state change* — on creation
and on every subsequent mutation:

```python
--8<-- "guides/getting-started/tutorial/ch04.py:aggregate"
```

The `order_must_have_items` invariant runs whenever the Order is created
or modified. If the items list is empty, it rejects the change:

```python
>>> Order(customer_name="Alice")
ValidationError: {'_entity': ['An order must contain at least one item']}
```

Notice that the invariant runs automatically — we don't call it
ourselves. Protean guarantees that the aggregate is always in a valid
state.

## Pre-Invariants: Guarding Transitions

A **pre-invariant** is checked *before* state changes are applied. We
use it to prevent invalid operations:

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
>>> order.customer_name = "Bob"
ValidationError: {'_entity': ['Cannot modify an order that has been shipped']}
```

## Aggregate Methods

Rather than mutating aggregate fields directly, we encapsulate behavior
in methods:

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

Methods become the **public API** of the aggregate. External code calls
`order.confirm()` rather than `order.status = "CONFIRMED"`. This keeps
business logic inside the aggregate where invariants can enforce it.

## Putting It Together

```python
--8<-- "guides/getting-started/tutorial/ch04.py:usage"
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

Notice how every rule is enforced automatically — the aggregate never
enters an invalid state.

## What We Built

- **Post-invariants** (`@invariant.post`) that validate state after every
  change, keeping the aggregate always consistent.
- **Pre-invariants** (`@invariant.pre`) that guard state transitions,
  preventing invalid operations.
- **Aggregate methods** that encapsulate business logic and serve as the
  public API for state changes.

We now have a rich domain model with aggregates, entities, value objects,
and business rules.

!!! success "DDD Milestone"
    You have built a complete **DDD domain model** — aggregates, entities,
    value objects, and invariants. These concepts are the foundation for
    every Protean application, regardless of architecture.

    If you are following the **pure DDD** approach, your next step is
    [Application Services](../../change-state/application-services.md) to
    wire use cases. See the [DDD Pathway](../../pathways/ddd.md) for the
    full reading order.

    The remaining chapters add **CQRS patterns** — Commands, Projections,
    and separated read/write models — on top of this foundation.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch04.py:full"
```

## Next

[Chapter 5: Commands and Handlers →](05-commands.md)
