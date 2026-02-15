# Internals

This section documents the design reasoning and internal architecture of
Protean's core systems. It is intended for contributors, advanced users, and
anyone who wants to understand **why** Protean works the way it does — not
just how to use it.

These pages go deeper than the guides. Where guides show you what to write,
internals explain the machinery that makes it work and the decisions that
shaped it.

## Topics

- [Field system](./field-system.md) -- How Protean's field functions translate
  domain vocabulary into Pydantic's type system, and why three definition
  styles are supported.
- [Shadow fields](./shadow-fields.md) -- How ValueObject and Reference fields
  are flattened into database columns via shadow fields, and why they live
  outside Pydantic's model fields.
- [Query system](./query-system.md) -- How the Repository → DAO → QuerySet →
  Provider chain works, Q object expression trees, lookup resolution, lazy
  evaluation, and entity state tracking.
