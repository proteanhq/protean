# Protean agent instructions

This is the canonical AGENTS.md source that ships inside the `protean` package.
It is version-coupled to the framework: a coding agent reading it always sees
the guidance that matches the installed version.

`protean dx install` renders this source into a project's `AGENTS.md`, the
`CLAUDE.md` bridge, and the per-tool rule files. Until that command lands, the
source is reachable through `protean.dx.load_agents_source()`.

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
