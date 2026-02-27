# Entities

## Why Entities?

Not every concept in a domain stands on its own. An `OrderItem` only makes
sense within an `Order`; a `Reservation` belongs to a `Booking`. These
objects have their own identity — you need to distinguish one line item from
another — but they don't manage their own lifecycle. If you modeled every
identified object as an independent aggregate, you'd lose the ability to
enforce rules that span the parent and its children (e.g. "an order's total
must equal the sum of its line items").

Entities are the answer: objects with unique, stable identity that live
*inside* an aggregate. The aggregate root controls their creation, mutation,
and deletion, ensuring that cross-object invariants are always satisfied.

Entities are very similar to [Aggregates](./aggregates.md) in nature and
purpose. In fact, an Aggregate is nothing but an entity chosen to represent
the entire cluster.

Entities are mutable and encapsulate both state and behavior. They have
distinct identity. This identity remains consistent throughout
the life of the entity, regardless of changes to its attributes.

## Facts

### Entities have an identity. { data-toc-label="Identity" }
The primary characteristic of an entity is its unique identity, which
distinguishes it from other objects. This identity is independent of the
entity's attributes and remains constant throughout the entity's lifecycle.

### Entities are mutable. { data-toc-label="Mutability" }
Entities can change state over time while maintaining their identity.
This mutability is essential for modeling real-world objects that undergo
various state changes.

### Entities can contain other entities or value objects. { data-toc-label="Composition" }
Entities can compose other entities and [value objects](./value-objects.md),
enabling the modeling of complex domain relationships. However, care should be
taken to manage the complexity and maintain the boundaries of aggregates.

### Entities enforce business rules. { data-toc-label="Business Rules" }
Entities are responsible for ensuring that business rules and invariants are
upheld within their scope. They encapsulate the logic necessary to maintain
domain integrity.

### Entities in one domain can be value objects in another. { data-toc-label="Entity or Value Object?" }
Entities in one domain can be a [Value Object](./value-objects.md) in another.

For example, a seat is an Entity in the Theatre domain if the theatre allocate
seat numbers to patrons. If visitors are not allotted specific seats, then a
seat can be considered a ValueObject, as one seat can be exchanged with another.

### Aggregates handle entity persistence.  { data-toc-label="Persistence" }
Entities are persisted and retrieved through their aggregates. They should not
be queried or updated directly, as it can lead to an invalid state because of
unsatisfied domain invariants.

### Entities are related through associations. { data-toc-label="Associations" }
Associations define how entities are connected. These associations are
typically managed within the context of an aggregate to ensure consistency and
integrity.

### Entities can contain nested entities and value objects. { data-toc-label="Nested Objects" }
Entities can nest other entities and value objects to form hierarchical
structures. These nested objects are managed as part of the aggregate's
lifecycle and contribute to the overall state of the entity.

### Entity graphs should be kept manageable. { data-toc-label="Nesting" }
While entities can form complex graphs, it is crucial to maintain manageable
structures to avoid excessive complexity. To ensure performance and
manageability, entities should be part of aggregates that are appropriately
sized. If an aggregate becomes too large, consider splitting it into smaller,
more manageable aggregates.

---

## Next steps

For practical details on defining and using entities in Protean, see the guide:

- [Entities](../../guides/domain-definition/entities.md) — Defining entities, configuration options, and associations within aggregates.

Not sure whether your concept should be an entity, aggregate, or value object?

- [Choosing Element Types](./choosing-element-types.md) — Decision guide with checklists and flowcharts.

For design guidance:

- [Design Small Aggregates](../../patterns/design-small-aggregates.md) — Drawing the right boundaries between aggregates and entities.
- [Encapsulate State Changes](../../patterns/encapsulate-state-changes.md) — Protecting internals with controlled mutation.
