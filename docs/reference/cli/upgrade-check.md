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

## What options does the command take?

| Option | Default | Description |
|--------|---------|-------------|
| `--domain` / `-d` | `.` | Path to the domain module (e.g. `my_app.domain`) |
| `--format` / `-f` | `rich` | Output format: `rich` or `json` |
| `--opportunities` | off | Report shipped capability the domain still hand-rolls, instead of the readiness checks (see [Opportunities](#opportunities-what-you-hand-roll-that-the-framework-now-ships)) |
| `--pinned-version` | installed Protean | The version the domain is pinned to, for `--opportunities` |

The domain is initialized so the schema check can introspect the configured
databases. `--opportunities` skips that init: those detectors only read your
source, so the mode runs with the databases and brokers down.

## Exit codes

| Exit code | Meaning |
|-----------|---------|
| `0` | No findings, or only advisory (`info`) findings. |
| `1` | At least one `warning` finding, including `CHECK_FAILED`. |
| `2` | A usage or environment error: a bad `--format`, a bad or misplaced `--pinned-version`, an unknown option, a domain that does not load, an error while the domain initializes, or an error outside a single check. A check that fails on its own reports `CHECK_FAILED` and exits `1`. The message goes to stderr, and stdout stays empty, including under `--format json`. |

`--format json` prints the findings as a plain JSON list. It does not use the
[result envelope](conventions.md#what-does-the-result-envelope-contain).

## Which changes does the command check?

| Code | Level | Surface | What it reports |
|------|-------|---------|-----------------|
| `POOL_DEFAULTS_CHANGED` | warning | Config | A SQL database with `pool_size` unset. 0.16 raised the SQLAlchemy pool defaults to `pool_size=5`, `max_overflow=10`. |
| `HEALTH_PORT_BIND` | info | Config | `protean server` runs a health-check server on port 8080; 0.17 changed its default bind host to loopback (`127.0.0.1`), so probes are no longer reachable off-host unless you set `host = "0.0.0.0"`. |
| `ELASTICSEARCH_SERVER_V8` | warning | Infra | An Elasticsearch provider; installs now default to the v8 client, which requires an Elasticsearch 8.x server. |
| `OUTBOX_NEEDS_ALTER` | warning | Schema | A live `outbox` table with unbounded string columns; emits the exact backend `ALTER` to apply the new `VARCHAR(N)` bounds. |
| `NESTED_UNIT_OF_WORK` | warning | Source | A `with UnitOfWork()` block opened inside another. After ADR-0027 it joins the outer transaction with no savepoints, so a nested rollback dooms the whole thing. |
| `UNIT_OF_WORK_NESTING_REVIEW` | info | Source | No lexical nesting found, but nesting through a call cannot be seen statically. Reports how many blocks are worth walking. |
| `IO_INSIDE_UNIT_OF_WORK` | warning | Source | An HTTP call, broker publish or email send inside a `with UnitOfWork()` block, which now holds database locks for the length of the call. |
| `OUTBOX_TARGET_BROKER_NULLABLE` | warning | Schema | A live `outbox` table whose `target_broker` still allows NULL. Emits the backfill plus the `SET NOT NULL` for your dialect. Shipped in 0.16.2; reaches `main` in 0.17. |
| `OUTBOX_UNIQUE_INDEX_LEGACY` | warning | Schema | A live `outbox` table still carrying the `message_id`-only unique index. Emits the swap to the composite `(message_id, target_broker)` index that the dual-write idempotency guard depends on. |
| `CHECK_FAILED` | warning | — | A check could not complete (e.g. the database was unreachable); the report may be incomplete for that area. |

### What the source checks cover

`NESTED_UNIT_OF_WORK`, `UNIT_OF_WORK_NESTING_REVIEW` and
`IO_INSIDE_UNIT_OF_WORK` read `with UnitOfWork():` and `async with
UnitOfWork():` blocks, where the statement calls `UnitOfWork` by that name. The
scan does not see a Unit of Work opened any other way: through an alias (`from
protean import UnitOfWork as U`), through a variable (`uow = UnitOfWork()` and
then `with uow:`), or with `uow.start()`. The scan reads modules in the
domain's own directory and its direct subdirectories. Modules nested deeper are
not read.

A clean report can still miss three cases:

- **The Unit of Work the framework opens for you.** The framework runs every
  `@handle` method (event handlers, command handlers, projectors and process
  managers) and every `@use_case` method inside a Unit of Work that no `with`
  statement shows. The scan cannot see it. An explicit `with UnitOfWork()`
  block inside one of these methods is still scanned, and I/O inside it is
  reported. The block is nested inside the framework's Unit of Work, though,
  and `NESTED_UNIT_OF_WORK` does not report that. `protean check` has no
  nesting rule, so neither tool reports this case. Search your handler and
  `@use_case` methods for `UnitOfWork` by hand.
- **I/O in a method body with no explicit block.** For `@handle` methods, run
  `protean check`. It reports a method that calls out after its first
  `repository_for(...)` as
  [`HANDLER_PERSISTS_AND_CALLS_OUT`](../fitness-functions.md#handler-persists-and-calls-out),
  at `info` level. An `info` finding does not change the exit code unless you
  set `[lint].level = "info"` (see [`protean check`](check.md#exit-codes)).
  `protean check` does not read `@use_case` methods, so review those by hand.
- **I/O the rules do not recognise.** `upgrade-check` and `protean check` count
  a call as I/O in two cases. An HTTP verb (`get`, `post`, `send` and the like)
  counts when it is called on `httpx`, `requests`, `urllib`, `urllib3`,
  `aiohttp` or `smtplib`, or on a name imported from one of them. A call named
  `publish`, `send_email`, `sendmail`, `send_message` or `urlopen` also counts.
  `upgrade-check` counts it on any receiver. `protean check` counts it only
  when the call resolves to an imported name. It therefore misses a call on an
  object held on `self` or in a local variable. Neither tool flags a method
  with another name on an injected port or adapter (`self.gateway.charge()`).
  Neither tool flags a call into a client library outside that list either,
  such as `stripe` or `boto3`.

## Review the SQL the command generates

For `OUTBOX_NEEDS_ALTER`, the command introspects the live table and emits the
`ALTER` tailored to the connected database, for example on PostgreSQL:

```sql
ALTER TABLE outbox
  ALTER COLUMN message_id TYPE varchar(255),
  ALTER COLUMN status TYPE varchar(32),
  ...
```

Review the output to confirm that no existing value exceeds the new bounds.
Then run the `ALTER`. Protean never applies the migration for you: schema
changes are an adapter/operator concern, as the release workflow and
breaking-change policy states
([ADR-0004](../../adr/0004-release-workflow-and-breaking-change-policy.md)).

See the [v0.16 migration guide](../migration/v0-16.md) for the full upgrade notes.

## Opportunities: what you hand-roll that the framework now ships

The checks above report what needs attention when you move *up* a release.
`--opportunities` reports the other direction: capability the framework has
already shipped that your domain still appears to hand-roll. A codebase written
against an older Protean keeps its hand-rolled queue table, its custom
middleware and its raw SQL long after the framework added the same capability.
The code stays because nobody goes back to re-check it. The `--opportunities`
mode lists each of those places in your code.

```bash
protean upgrade-check --opportunities --domain=my_app
protean upgrade-check --opportunities --domain=my_app --pinned-version=0.15
protean upgrade-check --opportunities --domain=my_app --format=json
```

Every detector is **deterministic**, so it gives the same findings every run.
It reads your source and matches on its structure: imports, call shapes, and
the literal choices in a field. The raw-SQL detector is import-gated: `text` is
matched only when it comes from `sqlalchemy`. The middleware detector matches a
`BaseHTTPMiddleware` subclass or a `dispatch` method. It also matches an
`add_middleware` call that names something outside the framework's own
middlewares and the standard Starlette and FastAPI ones. The queue-status
detector reads a `status` or `state` field and needs at least two
queue-vocabulary choices before it fires. Detector findings are advisory
(`info`) and do not change the exit code. The one exception is `CHECK_FAILED`:
if a detector cannot complete, that is a `warning`, and any warning exits `1`.

### How does the pinned version filter findings?

Each detector declares the release its capability arrived in. A finding is
reported only when that release is at or below the *pinned* version, i.e. you
already have the capability installed but still hand-roll it. The pinned
version defaults to the installed Protean. `--pinned-version` overrides the
default. With it, you can ask "what has arrived since the release this code was
written against". Pinning below a capability's release suppresses that
capability's finding, because you do not own it yet.

`--pinned-version` takes `MAJOR.MINOR` with an optional patch and an optional
release tag: `0.16`, `0.16.3`, `0.16.0rc1`, `0.16.0.dev1`. Anything else exits
`2`, so a typo does not silently read as some other version.

### Which hand-rolled code does each detector find?

| Code | Level | Capability (release) | What it finds |
|------|-------|----------------------|---------------|
| `OPPORTUNITY_QUERY_API` | info | Query API (0.16.0) | Raw `sqlalchemy.text(...)` SQL sites. The query API (`Q(field__isnull=)`, `F()`, `QuerySet.count()`, `.only()`, `.all(with_total=False)`, dispatched through `@domain.query_handler` and `domain.dispatch()`) covers most of what raw SQL is reached for. The `text` name is import-gated to `sqlalchemy`, so an unrelated `text(` call is not flagged. |
| `OPPORTUNITY_DOMAIN_CONTEXT_MIDDLEWARE` | info | `DomainContextMiddleware` (0.15.0) | A custom ASGI middleware: a `BaseHTTPMiddleware` subclass, a class with `async def dispatch(self, request, call_next)`, or an `app.add_middleware(...)` of a class the framework does not ship. `DomainContextMiddleware` wires domain context plus correlation-id propagation, and registering it (or a standard Starlette/FastAPI middleware like `CORSMiddleware` or `GZipMiddleware`) is not flagged. |
| `OPPORTUNITY_OUTBOX` | info | Outbox (0.14.0) | A status/state field whose choices cycle through queue states (pending / processing / done / failed). That is usually a hand-rolled work queue the outbox (retry, backoff, DLQ) now covers. The match needs a queue-like choice set, so a plain `status` with business choices does not fire. |
| `SANITIZE_DEFAULT_CHANGED` | info | Sanitize default flip (0.18.0) | A `String`/`Text` field that leaves `sanitize` unset, either by not passing it or by passing `None`, and therefore relied on the pre-0.18 default of `sanitize=True`. Every site is listed by `module:line` so the finding works as a migration checklist. Not flagged: a field that declares `sanitize` by keyword or positionally (`Text(True)`), a field with a real `choices=` value (never sanitized), a container content spec (`List(String(...))`, never sanitized), a `String`/`Text` that is not Protean's, and a field whose arguments hide behind a splat (`String(**opts)`). The whole finding is suppressed when the domain sets `[field_defaults] sanitize = true`, which opts every unset field back into the old behaviour. See [the migration guide](../migration/v0-18.md#string-and-text-no-longer-sanitize-by-default). |
| `CHECK_FAILED` | warning | n/a | A detector could not complete; the report may be incomplete for that area. |

### Which advice does this mode leave out?

`--opportunities` ships only deterministic detectors, so the report gives the
same verdict every run. Most of the detectors report a capability that the
framework now ships and the domain still writes by hand.
`SANITIZE_DEFAULT_CHANGED` is the exception: it reports a behaviour change, the
0.18.0 sanitize-default flip, whose effect is silent at runtime. It works the
same way, a deterministic source scan gated on the release. Protean's
open-source release does not give advice that needs judgment ("this
orchestration is really a process manager"). Under the open-core model, the
commercial Domain Assessment gives that advice, because its findings are not
deterministic.

!!! warning "A warning exit is easier to hit from 0.17"

    `NESTED_UNIT_OF_WORK` and `IO_INSIDE_UNIT_OF_WORK` are both warnings. Both
    checks read your source code and ignore your config. If you change nothing,
    `upgrade-check` can exit `0` on 0.16 and non-zero on 0.17 for the same
    domain. On 0.17 and 0.18 a warning exits `2`. From 0.19 a warning exits `1`
    and a failed run exits `2`. See [`upgrade-check` exits 1 for warnings and 2
    for
    errors](../migration/v0-19.md#upgrade-check-exits-1-for-warnings-and-2-for-errors).
    See [the 0.17 migration
    guide](../migration/v0-17.md#the-unit-of-work-is-a-real-transaction) for
    what `NESTED_UNIT_OF_WORK` and `IO_INSIDE_UNIT_OF_WORK` mean.
