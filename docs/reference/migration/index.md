# Migration Guides

Guides for upgrading between Protean versions.

- [**v0.19 Migration**](./v0-19.md): Outbox rows of equal priority are claimed
  in commit order. The `ix_outbox_active` index needs a one-time rebuild.
  Generated `.proto` files import each other. Generated Avro schemas write
  `Identifier` fields as plain strings. The email port is removed. A
  state-based aggregate's events are saved only through `add()`. `ir diff`
  exits 3 for non-breaking changes and 2 for errors. `upgrade-check` exits 1
  for warnings and 2 for errors.
- [**v0.18 Migration**](./v0-18.md): You install the web, shell and scaffolder
  dependencies through install extras. PostgreSQL defaults to psycopg 3.
  `check` and `verify` write their output in one shared envelope format. The
  cache API returns the same results on every adapter. String fields no longer
  sanitize by default. A subscription now runs retry and dead-lettering.
- [**v0.17 Migration**](./v0-17.md): The Unit of Work becomes a real
  transaction. The guide also covers the 1.0 API surface (`event_sourced`
  option, internalized `is_fact_event`), stream trimming, and the email
  subsystem deprecation.
- [**v0.16 Migration**](./v0-16.md): Outbox column bounds and upgrade steps for v0.16.
- [**v0.15 Migration**](./v0-15.md): Breaking changes and upgrade steps for v0.15.
