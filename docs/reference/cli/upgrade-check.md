# `protean upgrade-check`

Reports the changes that need attention when upgrading a domain to Protean 0.16,
with concrete remediation. It is **read-only**: schema changes are *generated* as
SQL for you to review and run, never applied automatically.

```bash
protean upgrade-check --domain=my_app
protean upgrade-check --domain=my_app --format=json
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--domain` / `-d` | `.` | Path to the domain module (e.g. `my_app.domain`) |
| `--format` / `-f` | `rich` | Output format: `rich` or `json` |

The domain is initialized so the schema check can introspect the configured
databases. Exit code is `0` when only advisory (info) findings are present and
`2` when any warnings need review.

## Checks

| Code | Level | Surface | What it reports |
|------|-------|---------|-----------------|
| `STATUS_SELF_TRANSITION` | info | Element | Status fields whose transition maps omit self-loops. 0.16 rejects assigning a status to its current value unless the state lists itself as a target. |
| `POOL_DEFAULTS_CHANGED` | warning | Config | A SQL database with `pool_size` unset. 0.16 raised the SQLAlchemy pool defaults to `pool_size=5`, `max_overflow=10`. |
| `HEALTH_PORT_BIND` | info | Config | `protean server` now binds a health-check server on port 8080 by default. |
| `ELASTICSEARCH_SERVER_V8` | warning | Infra | An Elasticsearch provider; installs now default to the v8 client, which requires an Elasticsearch 8.x server. |
| `OUTBOX_NEEDS_ALTER` | warning | Schema | A live `outbox` table with unbounded string columns; emits the exact backend `ALTER` to apply the new `VARCHAR(N)` bounds. |

## Generated SQL

For `OUTBOX_NEEDS_ALTER`, the command introspects the live table and emits the
`ALTER` tailored to the connected database, for example on PostgreSQL:

```sql
ALTER TABLE outbox
  ALTER COLUMN message_id TYPE varchar(255),
  ALTER COLUMN status TYPE varchar(32),
  ...
```

Review the output, confirm no existing value exceeds the new bounds, then run it.
Protean never applies the migration for you: schema changes are an
adapter/operator concern (see [ADR-0004](../../adr/0004-release-workflow-and-breaking-change-policy.md)).

See the [v0.16 migration guide](../migration/v0-16.md) for the full upgrade notes.
