# Value Objects

## Why Value Objects?

Representing domain concepts as raw primitives — a `str` for an email
address, a `float` for a monetary amount, two `float`s for GPS
coordinates — is one of the most common sources of bugs in domain code.
Validation logic gets duplicated everywhere the value is used, invalid
states slip through because there's no single place that enforces the
rules, and the code loses expressiveness ("What does this `str` parameter
actually represent?").

Value objects solve this by wrapping related attributes and their
validation rules into a single, immutable, self-validating concept.
An `Email` value object guarantees that every instance is a well-formed
email address. A `Money` value object keeps amount and currency together
so you never accidentally add dollars to euros.

Value objects are immutable domain elements that are distinguished by their
properties rather than their identity. They are used to represent concepts in
the domain that have no unique identity but are defined by their attributes.

## Facts

### Value Objects are immutable. { data-toc-label="Immutable" }
Once created, the state of a value object cannot be changed. This immutability
ensures that value objects preserve their integrity and consistency.

### Value Objects are defined by their attributes. { data-toc-label="Data-based definition" }
The identity of a value object is based entirely on its attributes.
Two value objects with the same attribute values are considered equal,
regardless of their instance.

### Value Objects are often used for descriptive purposes. { data-toc-label="Descriptive" }
Value objects are ideal for representing descriptive aspects of the domain,
such as measurements, monetary values, or other concepts that are defined by
their values.

### Value Objects enforce business rules. { data-toc-label="Enclose Business Rules" }
Value objects can encapsulate business rules and constraints related to their
attributes. They ensure that the values they hold are always valid and
consistent.

### Value Objects are nested within entities. { data-toc-label="Enclosed in Entities" }
Value objects are enclosed within [aggregates](./aggregates.md) and
[entities](./entities.md) to represent complex attributes.

### Value Objects are persisted with entities. { data-toc-label="Persisted within Entities" }
Value objects are typically persisted as part of the
[entities](./entities.md) or [aggregates](./aggregates.md) they belong to.
Their persistence is managed implicitly through the enclosing entity or
aggregate.

When an entity is persisted, any value objects it contains
are also persisted. This ensures that the complete state of the entity,
including its descriptive attributes, is stored.

### Value Objects can be composed of Value Objects. { data-toc-label="Nesting" }
Value objects can be composed to form complex types, but they do not have
independent identity and are always part of entities or aggregates.

### Value Objects support functional updates. { data-toc-label="Functional Updates" }
Since value objects are immutable, they provide a `replace()` method to create
a new instance with selected fields changed — the functional equivalent of
mutation. Invariants are re-validated on the new instance.

### Value Objects can project entity structure. { data-toc-label="Entity Projections" }
Value objects can be auto-generated from entity classes using
`value_object_from_entity()`, eliminating field duplication when carrying
entity data in commands and events. The inverse operation,
`Entity.from_value_object()`, converts the VO back into an entity instance.

### Value Objects do not reference entities. { data-toc-label="No References" }
Value objects should not hold references to entities. They are self-contained
and defined solely by their attributes.

---

## Next steps

For practical details on defining and using value objects in Protean, see the guide:

- [Value Objects](../../guides/domain-definition/value-objects.md) — Defining value objects, embedding them in aggregates, invariants, and equality semantics.

Not sure whether your concept should be a value object, entity, or aggregate?

- [Choosing Element Types](./choosing-element-types.md) — Decision guide with checklists and flowcharts.

For design guidance:

- [Replace Primitives with Value Objects](../../patterns/replace-primitives-with-value-objects.md) — When and why to wrap raw types in domain-specific value objects.
