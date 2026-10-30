# Protean agent instructions

## Working with Protean

- Model the domain with the decorators on the `Domain` object: `@domain.aggregate`,
  `@domain.entity`, `@domain.value_object`, `@domain.event`, `@domain.command`.
- Keep one aggregate per transaction. Cross-aggregate consistency is eventual,
  carried by events.
- Put validation in the domain layer: field constraints, value-object invariants,
  and aggregate invariants. The database stores state; it does not enforce the
  business rules.
