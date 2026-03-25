# Define Domain Elements

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

This section covers how to model your business concepts as domain elements
in Protean -- aggregates, entities, value objects, events, and the
relationships between them.

For the conceptual foundations behind these patterns, see
[Building Blocks](../../concepts/building-blocks/index.md).

## What's in This Section

### [Aggregates](./aggregates.md)

Define your root entities -- the coarse-grained building blocks that
encapsulate business logic, enforce invariants, and define transaction
boundaries. Start here when modeling a new domain concept.

### [Entities](./entities.md)

Add child objects with unique identity inside an aggregate. Entities are
always accessed through their parent aggregate and share its lifecycle.

### [Value Objects](./value-objects.md)

Model immutable descriptive concepts like Money, Email, or Address. Value
objects are defined by their attributes, not identity, and are embedded
within aggregates or entities.

### [Relationships](./relationships.md)

Connect domain elements with `HasOne`, `HasMany`, and `Reference` fields.
Express one-to-one, one-to-many, and cross-aggregate references.

### [Events](./events.md)

Define domain events -- immutable records of state changes that enable
decoupled communication between different parts of your system. Events
can be processed synchronously or asynchronously.

## Related

- [Identity](../../reference/domain-elements/identity.md) -- Configure
  identity strategies, types, and custom generators.
- [Fields Reference](../../reference/fields/index.md) -- All field types,
  arguments, and definition styles.
- [Choosing Element Types](../../concepts/building-blocks/choosing-element-types.md)
  -- Guidance on when to use an aggregate vs. entity vs. value object.
