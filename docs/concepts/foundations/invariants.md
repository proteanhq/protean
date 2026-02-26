# Invariants

An invariant is a business rule or condition that must always hold true within a domain concept. Invariants protect the consistency and validity of the domain model -- they are the reason [aggregates](../building-blocks/aggregates.md) exist. The aggregate boundary is drawn around the data that must be consistent to satisfy a set of invariants.

If a system allows an order total to disagree with the sum of its line items, or permits a bank account balance to go negative when the account type forbids it, the domain model has failed at its most fundamental job. Invariants prevent these invalid states from ever occurring.

## Types of Invariants

Invariants operate at different levels of granularity:

- **Field-level constraints.** Basic type and format rules: an email must be a valid format, a quantity must be positive, a status must be one of an enumerated set of values. These are the simplest invariants and are enforced at the field level.

- **Value object invariants.** Rules within a single value object that ensure the concept it represents is always valid. A `Money` value object might enforce that the amount is non-negative and the currency code is a recognized ISO standard.

- **Aggregate-level invariants.** Rules spanning multiple objects within the aggregate cluster. The sum of line item totals must equal the order total. A reservation cannot overlap with another reservation for the same resource. These are the invariants that define why certain objects are grouped into the same aggregate.

- **Cross-aggregate invariants.** Rules spanning multiple aggregates. An order can only be placed if the customer's credit limit allows it, but the customer and the order are separate aggregates. These invariants cannot be enforced within a single transaction and are handled through eventual consistency via [domain events](../building-blocks/events.md).

## The Always-Valid Guarantee

Protean enforces a strict design principle: **an aggregate cluster can never
exist in an invalid state.** Once you define field constraints, value object
rules, or aggregate invariants, Protean ensures they hold at all times -- not
just when you explicitly ask for validation, but after every single field
change.

This works because Protean intercepts every attribute assignment on aggregates
and entities. When you write `order.total_amount = 50.0`, the framework
automatically:

1. **Runs pre-invariants** (`@invariant.pre`) on the aggregate root before
   the field is set.
2. **Validates the field value** against its type, constraints (`required`,
   `max_length`, `min_value`, `choices`), and any custom validators.
3. **Sets the field.**
4. **Runs post-invariants** (`@invariant.post`) on the aggregate root after
   the field is set.

If any check fails, a `ValidationError` is raised and the field is not
changed. The aggregate stays in its previous valid state.

This enforcement is **recursive across the entire aggregate cluster.** When an
invariant runs on the aggregate root, Protean also runs invariants on all
associated entities (via `HasOne` and `HasMany`). A child entity deep within
the cluster cannot silently violate its own invariants -- they are checked
whenever the aggregate root's invariants are checked.

```python
@domain.aggregate
class Order:
    total_amount = Float(required=True)
    items = HasMany("OrderItem")

    @invariant.post
    def total_must_equal_sum_of_items(self):
        expected = sum(item.subtotal for item in self.items)
        if self.total_amount != expected:
            raise ValidationError(
                {"_entity": ["Total should be sum of item prices"]}
            )

# This raises ValidationError -- the invariant fires immediately
order.total_amount = 50.0  # But items sum to 100.0
```

### Batching Changes with `atomic_change`

Sometimes you need to make multiple related changes that would individually
violate an invariant but are collectively valid. Protean provides the
`atomic_change` context manager for this:

```python
from protean.core.aggregate import atomic_change

with atomic_change(order):
    order.total_amount = 120.0               # Would fail invariant alone
    order.add_items(OrderItem(subtotal=20))   # But together they're consistent
# Invariants checked ONCE on exit -- both changes are valid together
```

Inside the block, invariant checks are suspended. A pre-check runs on entry
and a post-check runs on exit. If the post-check fails, a `ValidationError`
is raised.

### Why This Matters

The always-valid guarantee means you can mutate aggregates safely anywhere in
your code without worrying about putting them into an inconsistent state. You
don't need to remember to call a `validate()` method. You don't need to check
validity before persisting. The aggregate simply refuses to accept invalid
changes.

This has several consequences for application design:

- **Named methods on aggregates are safe by default.** A method like
  `order.place()` can set multiple fields, and invariants will catch any
  inconsistency on each assignment (or use `atomic_change` for batched
  mutations).
- **Handlers can't corrupt domain state.** Even if a command handler sets
  fields directly rather than using named methods, invariants will still fire.
- **Testing is simpler.** You can test invariants by directly setting fields
  and asserting that `ValidationError` is raised -- no need to go through
  handlers or repositories.

## Invariants Define Aggregate Boundaries

The most important design principle for aggregates is this: **group together the data that must be consistent to enforce an invariant.**

If two pieces of data never need to be consistent within the same transaction, they likely belong in different aggregates. If they do need to be consistent, they must be in the same aggregate so that invariants can be checked atomically.

This is why aggregates should be small. The fewer invariants an aggregate enforces, the smaller its consistency boundary, and the less contention it creates in a concurrent system.

## Invariants and Domain Events

When invariants span aggregate boundaries, they cannot be enforced synchronously. Instead, one aggregate raises an event, and another aggregate reacts by enforcing its own invariants based on the event data. This leads to eventual consistency -- a deliberate trade-off between strict transactional consistency and system scalability.

For example, when an `Order` is placed, it raises an `OrderPlaced` event. An event handler for the `Inventory` aggregate reacts by checking whether sufficient stock exists and reserving it. If stock is insufficient, the inventory aggregate raises its own event, which may trigger a compensation action on the order.

## Further Reading

- [Aggregates](../building-blocks/aggregates.md) -- invariant enforcement within aggregate boundaries
- [Invariants Guide](../../guides/domain-behavior/invariants.md) -- implementing invariants in Protean
- [Validation Layering](../../patterns/validation-layering.md) -- where different types of validation belong
