# Migration Guides

Guides for upgrading between Protean versions.

- [**v0.19 Migration**](./v0-19.md): Outbox rows of equal priority are claimed in commit order, the `ix_outbox_active` index needs a one-time rebuild, generated `.proto` files import each other, and the email port is removed.
- [**v0.18 Migration**](./v0-18.md): The web, shell and scaffolder dependencies move behind install extras, PostgreSQL defaults to psycopg 3, `check` and `verify` output moves onto one envelope, the cache API answers the same way on every adapter, String fields stop sanitizing by default, and a subscription owns retry and dead-lettering.
- [**v0.17 Migration**](./v0-17.md): The Unit of Work becomes a real transaction, the 1.0 API surface (`event_sourced` option, internalized `is_fact_event`), stream trimming, and the email subsystem deprecation.
- [**v0.16 Migration**](./v0-16.md): Outbox column bounds and upgrade steps for v0.16.
- [**v0.15 Migration**](./v0-15.md): Breaking changes and upgrade steps for v0.15.
