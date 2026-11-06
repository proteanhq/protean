# How Protean works internally

The design reasoning and internal architecture behind Protean's core systems.
When you contribute to Protean, read these pages. Read them also to learn
**why** Protean works the way it does, beyond how to use it.

These pages give more detail than the guides. The guides show you what code to
write. These pages explain how Protean runs that code and why its design took
that form.

## What does each page explain?

- [Field system](./field-system.md): How Protean's field functions translate
  domain vocabulary into Pydantic's type system. The page also explains why
  Protean supports three definition styles.
- [Shadow fields](./shadow-fields.md): How Protean flattens ValueObject and
  Reference fields into database columns via shadow fields. The page also
  explains why shadow fields are not part of Pydantic's model fields.
- [Query system](./query-system.md): How the Repository → DAO → QuerySet →
  Provider chain works, Q object expression trees, lookup resolution, lazy
  evaluation, and entity state tracking.
- [Event sourcing](./event-sourcing.md): How `raise_()` invokes `@apply`
  handlers, aggregate reconstitution via `_create_for_reconstitution()` and
  `from_events()`, version tracking, invariant checking during replay, and
  causation chain traversal algorithms.
- [Event upcasting](./event-upcasting.md): How old event payloads are
  transparently transformed to the current schema during deserialization,
  chain building algorithm, validation, and integration with
  `Message.to_domain_object()`.
- [Intermediate Representation (IR)](./ir-specification.md): The portable JSON
  format for a domain model. It records the model's topology, its elements,
  their shape, and the links between them.
