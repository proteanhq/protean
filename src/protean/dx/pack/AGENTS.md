# Protean agent instructions

This is the canonical AGENTS.md source that ships inside the `protean` package.
It is version-coupled to the framework: a coding agent reading it always sees
the guidance that matches the installed version.

`protean dx install` renders this source into a project's `AGENTS.md` and a
one-line `CLAUDE.md` bridge, composed with the hard rules derived from the
diagnostics registry and stamped to the installed version.

<!-- dx-pack-seed: this is a placeholder source; the full corpus lands with the
developer-experience epic. -->

## Working with Protean

- Model the domain with the decorators on the `Domain` object: `@domain.aggregate`,
  `@domain.entity`, `@domain.value_object`, `@domain.event`, `@domain.command`.
- Keep one aggregate per transaction. Cross-aggregate consistency is eventual,
  carried by events.
- Put validation in the domain layer: field constraints, value-object invariants,
  and aggregate invariants. The database stores state; it does not enforce the
  business rules.
