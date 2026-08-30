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
| `--opportunities` | off | Report shipped capability the domain still hand-rolls, instead of the readiness checks (see [Opportunities](#opportunities-what-you-hand-roll-that-the-framework-now-ships)) |
| `--pinned-version` | installed Protean | The version the domain is pinned to, for `--opportunities` |

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
| `OUTBOX_TARGET_BROKER_NULLABLE` | warning | Schema | A live `outbox` table whose `target_broker` still allows NULL. Emits the backfill plus the `SET NOT NULL` for your dialect. Shipped in 0.16.2; reaches `main` in 0.17. |
| `OUTBOX_UNIQUE_INDEX_LEGACY` | warning | Schema | A live `outbox` table still carrying the `message_id`-only unique index. Emits the swap to the composite `(message_id, target_broker)` index that the dual-write idempotency guard depends on. |
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

## Opportunities: what you hand-roll that the framework now ships

The checks above report what needs attention when you move *up* a release.
`--opportunities` reports the other direction: capability the framework has
already shipped that your domain still appears to hand-roll. A codebase written
against an older Protean keeps its hand-rolled queue table, its custom
middleware, its raw SQL, long after the framework caught up, because nobody goes
back to re-check. This mode names those spots.

```bash
protean upgrade-check --opportunities --domain=my_app
protean upgrade-check --opportunities --domain=my_app --pinned-version=0.15
protean upgrade-check --opportunities --domain=my_app --format=json
```

Every detector is **deterministic**: it reads your source and matches on imports
and structure, never on bare names, so it gives the same findings every run and
does not fire on correct code. All findings are advisory (`info`), so this mode
does not change the exit code.

### The pinned version

Each detector declares the release its capability arrived in. A finding is
reported only when that release is at or below the *pinned* version, i.e. you
already have the capability installed but still hand-roll it. The pinned version
defaults to the installed Protean. `--pinned-version` overrides it, so you can
ask "what has arrived since the release this code was written against". Pinning
below a capability's release suppresses that capability's finding, because you do
not own it yet.

### Detectors

| Code | Level | Capability (release) | What it finds |
|------|-------|----------------------|---------------|
| `OPPORTUNITY_QUERY_API` | info | Query API (0.16.0) | Raw `sqlalchemy.text(...)` SQL sites. The query API (`Q(field__isnull=)`, `F()`, `QuerySet.count()`, `.only()`, `.all(with_total=False)`, dispatched through `@domain.query_handler` and `domain.dispatch()`) covers most of what raw SQL is reached for. The `text` name is import-gated to `sqlalchemy`, so an unrelated `text(` call is not flagged. |
| `OPPORTUNITY_DOMAIN_CONTEXT_MIDDLEWARE` | info | `DomainContextMiddleware` (0.15.0) | A custom ASGI middleware: a `BaseHTTPMiddleware` subclass, a class with `async def dispatch(self, request, call_next)`, or an `app.add_middleware(...)` of a class other than `DomainContextMiddleware`, which wires domain context plus correlation-id propagation. |
| `OPPORTUNITY_OUTBOX` | info | Outbox (0.14.0) | A status/state field whose choices cycle through queue states (pending / processing / done / failed). That is usually a hand-rolled work queue the outbox (retry, backoff, DLQ) now covers. The match needs a queue-like choice set, so a plain `status` with business choices does not fire. |
| `CHECK_FAILED` | warning | n/a | A detector could not complete; the report may be incomplete for that area. |

### Where the line is

This mode ships only deterministic detectors, so the report gives the same
verdict every run. Judgment-heavy advice ("this orchestration is really a process
manager") stays out of OSS; that is the commercial Domain Assessment surface, on
the non-deterministic side of the open-core boundary.

!!! warning "Exit code 2 is easier to hit in 0.17"

    The mapping is unchanged (any `warning` finding exits `2`), but
    `NESTED_UNIT_OF_WORK` and `IO_INSIDE_UNIT_OF_WORK` are both warnings, and
    both read your source rather than your config. A domain that exited `0` on
    0.16 can exit `2` on 0.17 with nothing changed. See
    [the migration guide](../migration/v0-17.md#the-unit-of-work-is-a-real-transaction)
    for what the two findings mean.
