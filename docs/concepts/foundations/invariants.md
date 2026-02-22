# Invariants

An invariant is a business rule or condition that must always hold true within a domain concept. Invariants protect the consistency and validity of the domain model -- they are the reason [aggregates](../building-blocks/aggregates.md) exist. The aggregate boundary is drawn around the data that must be consistent to satisfy a set of invariants.

If a system allows an order total to disagree with the sum of its line items, or permits a bank account balance to go negative when the account type forbids it, the domain model has failed at its most fundamental job. Invariants prevent these invalid states from ever occurring.

## Types of Invariants

Invariants operate at different levels of granularity:

- **Field-level constraints.** Basic type and format rules: an email must be a valid format, a quantity must be positive, a status must be one of an enumerated set of values. These are the simplest invariants and are enforced at the field level.

- **Value object invariants.** Rules within a single value object that ensure the concept it represents is always valid. A `Money` value object might enforce that the amount is non-negative and the currency code is a recognized ISO standard.

- **Aggregate-level invariants.** Rules spanning multiple objects within the aggregate cluster. The sum of line item totals must equal the order total. A reservation cannot overlap with another reservation for the same resource. These are the invariants that define why certain objects are grouped into the same aggregate.

- **Cross-aggregate invariants.** Rules spanning multiple aggregates. An order can only be placed if the customer's credit limit allows it, but the customer and the order are separate aggregates. These invariants cannot be enforced within a single transaction and are handled through eventual consistency via [domain events](../building-blocks/events.md).

## When Invariants Are Checked

Invariants should be validated before and after every state change. Pre-condition checks ensure the operation is valid given the current state ("can this order be cancelled?"). Post-condition checks ensure the resulting state satisfies all rules ("is the order total still consistent with its line items?").

If an invariant is violated, the state change is rejected. The aggregate remains in its previous valid state. This is a hard guarantee -- there is no "partially applied" state change that leaves the aggregate inconsistent.

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
