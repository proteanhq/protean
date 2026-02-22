# Identity

Identity is the property that distinguishes one domain object from all others. Two objects with the same attributes but different identities are different objects. Two objects with different attributes but the same identity are the same object at different points in time. This distinction is fundamental to Domain-Driven Design because it determines whether a concept should be modeled as an entity (has identity) or a [value object](../building-blocks/value-objects.md) (defined entirely by its attributes).

## Identity in Entities and Aggregates

Every [entity](../building-blocks/entities.md) and [aggregate](../building-blocks/aggregates.md) must have a unique identity. This identity persists across all state changes throughout the object's lifecycle. An order remains the same order whether it is "pending," "shipped," or "delivered." A customer remains the same customer whether they update their email address, change their name, or move to a new country.

The choice of identity is a modeling decision. **Natural keys** use a value that already exists in the domain -- an ISBN for a book, a tax ID for a business, an email address for a user account. **Surrogate keys** are generated values with no business meaning -- UUIDs, auto-incrementing integers, or timestamps. Each approach has trade-offs, but surrogate keys are generally preferred because they are stable, globally unique, and independent of business rules that may change.

## Identity Should Be Immutable

Once assigned, an identity never changes. This is a foundational invariant. If the "natural" identifier of a concept can change -- for example, a user's email address -- then that value is not a true identity. Use it as a regular attribute and assign a surrogate identity instead.

Immutable identity is what makes it safe to reference an aggregate from another aggregate, store it in an event, or use it as a correlation key across bounded contexts. If identity could change, every reference would risk becoming stale.

## When Identity Does Not Matter

Value objects have no identity. Two `Money(amount=10, currency="USD")` instances are interchangeable -- they are equal if their attributes are equal, and there is no need to track "which one" you are working with.

The decision between entity and value object often hinges on whether identity matters for the concept being modeled. If you need to track a specific instance over time and distinguish it from other instances with the same attributes, it is an entity. If you only care about what something *is* rather than *which one* it is, it is a value object.

## Generate Identity Early

A best practice in DDD is to generate identity at the point of creation, not at the database. When identity is assigned immediately, it is available for use in commands, events, and cross-aggregate references before the object is ever persisted. This eliminates an entire class of problems in distributed systems where objects need to be referenced before a round-trip to the database can occur.

Protean generates identities on object creation by default, following this principle.

## Further Reading

- [Aggregates](../building-blocks/aggregates.md) -- identity as the aggregate root's distinguishing property
- [Value Objects](../building-blocks/value-objects.md) -- the identity-less counterpart
- [Identity Guide](../../reference/domain-elements/identity.md) -- Protean-specific identity configuration and strategies
- [Creating Identities Early](../../patterns/creating-identities-early.md) -- the pattern in depth
