# `protean upgrade-check`

Reports the changes that need attention when upgrading a domain to a newer
Protean, with concrete remediation. The checks accumulate across releases rather
than targeting one, so the table below spans 0.16 and 0.17; each row says which
release the change came from. It is **read-only**: schema changes are
*generated* as SQL for you to review and run, never applied automatically.

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
| `POOL_DEFAULTS_CHANGED` | warning | Config | A SQL database with `pool_size` unset. 0.16 raised the SQLAlchemy pool defaults to `pool_size=5`, `max_overflow=10`. |
| `HEALTH_PORT_BIND` | info | Config | `protean server` runs a health-check server on port 8080; 0.17 changed its default bind host to loopback (`127.0.0.1`), so probes are no longer reachable off-host unless you set `host = "0.0.0.0"`. |
| `ELASTICSEARCH_SERVER_V8` | warning | Infra | An Elasticsearch provider; installs now default to the v8 client, which requires an Elasticsearch 8.x server. |
| `OUTBOX_NEEDS_ALTER` | warning | Schema | A live `outbox` table with unbounded string columns; emits the exact backend `ALTER` to apply the new `VARCHAR(N)` bounds. |
| `NESTED_UNIT_OF_WORK` | warning | Source | A `UnitOfWork` opened inside another. After ADR-0027 it joins the outer transaction with no savepoints, so a nested rollback dooms the whole thing. |
| `UNIT_OF_WORK_NESTING_REVIEW` | info | Source | No lexical nesting found, but nesting through a call cannot be seen statically. Reports how many blocks are worth walking. |
| `IO_INSIDE_UNIT_OF_WORK` | warning | Source | An HTTP call, broker publish or email send inside a `UnitOfWork`, which now holds database locks for the length of the call. |
| `CHECK_FAILED` | warning | — | A check could not complete (e.g. the database was unreachable); the report may be incomplete for that area. |

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

!!! warning "Exit code 2 is easier to hit in 0.17"

    The mapping is unchanged (any `warning` finding exits `2`), but
    `NESTED_UNIT_OF_WORK` and `IO_INSIDE_UNIT_OF_WORK` are both warnings, and
    both read your source rather than your config. A domain that exited `0` on
    0.16 can exit `2` on 0.17 with nothing changed. See
    [the migration guide](../migration/v0-17.md#the-unit-of-work-is-a-real-transaction)
    for what the two findings mean.
