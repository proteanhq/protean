# Invariants

An invariant is a business rule or condition that must always hold true within
a domain concept. You write invariants so that the domain model stays
consistent and valid. They are the reason
[aggregates](../building-blocks/aggregates.md) exist. You draw the aggregate
boundary around the data that must be consistent to satisfy a set of
invariants.

A system might let an order total disagree with the sum of its line items, or
let a bank account balance go negative while the account type forbids it. In
either case, the domain model has failed at its most fundamental job. Protean
checks invariants to stop these invalid states from ever occurring inside an
aggregate.

## Types of Invariants

Invariants operate at different levels of granularity:

- **Field-level constraints**: Basic type and format rules: an email must be a valid format, a quantity must be positive, a status must be one of an enumerated set of values. These are the simplest invariants and are enforced at the field level.

- **Value object invariants apply within a single value object**: their rules
  keep the value object's concept valid at all times. A `Money` value object
  might enforce that the amount is non-negative and the currency code is a
  recognized ISO standard.

- **Aggregate-level invariants span the aggregate cluster**: each rule covers
  multiple objects within the aggregate cluster. The sum of line item totals
  must equal the order total. A reservation cannot overlap with another
  reservation for the same resource. You group certain objects into the same
  aggregate because of these invariants.

- **Cross-aggregate invariants span multiple aggregates**: each rule covers
  data in more than one aggregate. An order can only be placed if the
  customer's credit limit allows it, but the customer and the order are
  separate aggregates. A single transaction cannot enforce these invariants, so
  you enforce them through eventual consistency via [domain
  events](../building-blocks/events.md).

## The Always-Valid Guarantee

Protean enforces a strict design principle: **an aggregate cluster can never
exist in an invalid state.** Protean checks the field constraints, value object
rules, and aggregate invariants you define after every single field change.
They hold at all times, and you do not need to ask for validation explicitly.

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
the cluster cannot silently violate its own invariants. They are checked
whenever the aggregate root's invariants are checked.

```python
--8<-- "concepts/foundations/invariants/001.py:model"
```

### Batching Changes with `atomic_change`

Sometimes you need to make multiple related changes that would individually
violate an invariant but are collectively valid. Protean provides the
`atomic_change` context manager for this:

```python
--8<-- "concepts/foundations/invariants/001.py:atomic_change"
```

Inside the block, invariant checks are suspended. A pre-check runs on entry
and a post-check runs on exit. If the post-check fails, a `ValidationError`
is raised.

### Why This Matters

The always-valid guarantee means you can mutate aggregates safely anywhere in
your code without worrying about putting them into an inconsistent state. You
don't need to remember to call a `validate()` method. You don't need to check
validity before persisting. The aggregate refuses to accept invalid
changes.

The always-valid guarantee has several consequences for application design:

- **Named methods on aggregates are safe by default**: A method like
  `order.place()` can set multiple fields, and Protean checks invariants on
  each assignment to catch any inconsistency (or use `atomic_change` for
  batched mutations).
- **Handlers can't corrupt domain state**: Even if a command handler sets
  fields directly rather than using named methods, invariants will still fire.
- **Testing is simpler**: You can test invariants by directly setting fields
  and asserting that `ValidationError` is raised. No need to go through
  handlers or repositories.

## Invariants Define Aggregate Boundaries

The most important design principle for aggregates is this: **group together the data that must be consistent to enforce an invariant.**

If two pieces of data never need to be consistent within the same transaction,
they likely belong in different aggregates. If they do need to be consistent,
they must be in the same aggregate. Only then can Protean check their
invariants atomically.

This is why aggregates should be small. An aggregate that enforces fewer
invariants has a smaller consistency boundary. A smaller consistency boundary
creates less contention in a concurrent system.

## Invariants and Domain Events

When invariants span aggregate boundaries, they cannot be enforced
synchronously. Instead, one aggregate raises an event, and another aggregate
reacts by enforcing its own invariants based on the event data. This leads to
eventual consistency, a deliberate trade-off between strict transactional
consistency and system scalability.

For example, when an `Order` is placed, it raises an `OrderPlaced` event. An
event handler for the `Inventory` aggregate reacts by checking whether
sufficient stock exists and reserving it. If stock is insufficient, the
inventory aggregate raises its own event. That event may trigger a compensation
action on the order.

## Further Reading

- [The Always-Valid Domain](../philosophy/always-valid.md): How the four
  validation layers work and what the always-valid guarantee means for your
  code
- [Aggregates](../building-blocks/aggregates.md): Invariant enforcement within aggregate boundaries
- [Invariants Guide](../../guides/domain-behavior/invariants.md): Implementing invariants in Protean
- [Validation Layering](../../patterns/validation-layering.md): Where different types of validation belong
