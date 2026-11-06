# Define Domain Elements

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

You model your business concepts as domain elements: aggregates, entities,
value objects, events, and the relationships between them.

For the conceptual foundations behind aggregates, entities, value objects, and
events, see [Building Blocks](../../concepts/building-blocks/index.md).

## Which guide do you need?

### [Aggregates](./aggregates.md)

Define your aggregates: coarse-grained root entities that encapsulate business
logic, enforce invariants, and define transaction boundaries. When you model a
new domain concept, start here.

### [Entities](./entities.md)

Add child objects with unique identity inside an aggregate. Entities are
always accessed through their parent aggregate and share its lifecycle.

### [Value Objects](./value-objects.md)

Model immutable descriptive concepts like Money, Email, or Address. Value
objects are defined by their attributes and have no identity. You embed them
within aggregates or entities.

### [Fields](./fields.md)

Declare attributes on your domain elements. The guide covers choosing a field
type, required fields, defaults, value constraints, custom validation, and
relationship fields.

### [Declaring Indexes](./indexes.md)

Declare the indexes your aggregates and entities need for fast queries:
composite, unique, partial, and covering indexes. You can also render the DDL
for review or migration tooling.

### [Identity](./identity.md)

Configure how aggregate and entity identifiers are generated. An identifier can
be a UUID, an integer, a user-supplied key, or the output of a custom function
you write yourself.

### [Relationships](./relationships.md)

Connect domain elements with `HasOne`, `HasMany`, and `Reference` fields.
Express one-to-one, one-to-many, and cross-aggregate references.

### [Events](./events.md)

Define domain events, immutable records of state changes that enable decoupled
communication between different parts of your system. Events can be processed
synchronously or asynchronously.

## Read more on fields, identity, and element types

- [Fields Reference](../../reference/fields/index.md): All field types,
  arguments, and definition styles.
- [Identity Reference](../../reference/domain-elements/identity.md): Every
  configuration option for identity strategies and types.
- [Choosing Element Types](../../concepts/building-blocks/choosing-element-types.md):
  Guidance on when to use an aggregate vs. entity vs. value object.
