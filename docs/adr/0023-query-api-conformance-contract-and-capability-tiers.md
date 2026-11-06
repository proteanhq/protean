# ADR-0023: Express the query API conformance contract through capability tiers

**Status:** Accepted

**Date:** July 2026

## Context

The outbox query-path remediation epic (#941) added a set of query and
persistence-path primitives that hot-path consumers depend on:

- `QuerySet.count()` / `BaseDAO._count`: count without materializing entities.
- `QuerySet.only()`: Project a subset of persisted fields into read-only
  `Record` objects.
- `isnull`, `lt`, `lte` lookups.
- `F`: Compare two columns of the same row inside a lookup.
- `BaseDAO._delete_top`: Bounded delete for batched cleanups.
- `BaseDAO._claim`: Atomic find-and-claim for concurrent consumers (ADR-0013).

Each primitive shipped with tests against one or two adapters (in-memory plus a
SQL backend, or an adapter-specific file). That left two gaps. First, adapter
divergence was invisible: no test asserted that the in-memory, SQLAlchemy, and
Elasticsearch backends agree on these primitives. A backend could diverge (a
missing lookup, a different empty-result shape) and no test would fail. Second,
the adapter-author self-check tool, `protean test test-adapter --provider=X`,
collects tests only from `tests/adapters/repository/generic/`. That directory
had no tests for these primitives, so the tool's capability report for adapter
authors said nothing about them.

Protean already has a capability-marker system for exactly this purpose. Each
database provider declares the capabilities it supports (`basic_storage`,
`transactional`, `atomic_transactions`, `raw_queries`, `schema_management`,
`native_json`, `native_array`). The runner selects the tests a given provider
must pass by matching each generic test's capability tag against that list. The
open question was how the new query-API primitives map onto that system: which
capability tier gates each primitive's conformance test, and therefore which
adapters must implement it.

## Decision

**The query-API contract is expressed through the existing capability-marker
system.** We do not introduce a separate mandatory/recommended/optional taxonomy
and we do not add new capability flags. A primitive's tier is the capability
marker that gates its conformance test in `tests/adapters/repository/generic/`.
An adapter that declares a capability must pass every generic test tagged with
that capability.

The capability assignments:

| Primitive | Capability marker | Adapters that must pass |
|---|---|---|
| `.count()` / `_count` | `basic_storage` | all (including Elasticsearch) |
| `.only()` projection | `basic_storage` | all |
| `isnull` lookup | `basic_storage` | all |
| `lt` / `lte` lookups | `basic_storage` | all |
| `_delete_top` bounded delete | `basic_storage` | all |
| `F()` column expression | `transactional` | in-memory + SQL (Elasticsearch exempt) |
| `_claim` correctness (single worker) | `transactional` | in-memory + SQL (Elasticsearch exempt) |
| `_claim` no-double-claim (concurrent) | `atomic_transactions` | SQL only |

Two placements need explanation because they do not follow the naive "everything
is `basic_storage`" reading.

**`F` is gated by the `transactional` marker instead of `basic_storage`.** The
Elasticsearch adapter raises `NotImplementedError` for `F`-bearing predicates
by design. Column-to-column comparison in Elasticsearch needs a Painless script
query, and the adapter does not implement one, so it raises an error instead of
returning divergent results. `F` is therefore supported by exactly the
in-memory and SQL backends. The same adapters carry the `transactional`
capability, and Elasticsearch does not. The `transactional` marker therefore
selects "in-memory + SQL, not Elasticsearch."" `F` itself does not need
transactions. The current adapters happen to split the same way, so the
`transactional` marker serves as the available "not-Elasticsearch, real-store"
selector. This is the same mechanism already used to gate `_claim` correctness.
Elasticsearch's loud-fail contract for `F` is covered separately by an
adapter-specific test, so the full contract (works on in-memory + SQL, fails
loudly on Elasticsearch) remains verified.

**`_claim` follows the atomic find-and-claim contract (ADR-0013) and is split
across two tiers.** The `transactional`-tier tests verify single-worker
correctness on in-memory and SQL: claimed rows returned in post-claim state,
`limit`/`order_by` honoured, durability, and no re-claim of already-claimed
rows. No-double-claim under concurrent workers requires real database-level
atomicity, so the `atomic_transactions`-tier tests verify it. SQL backends
carry the `atomic_transactions` tier and the in-memory store does not.
Relational backends uphold no-double-claim by one of three mechanisms: `FOR
UPDATE SKIP LOCKED` (the PostgreSQL fast path), serialized writers (SQLite), or
the portable guarded `UPDATE ... WHERE` re-evaluated under row-lock contention
(MSSQL), so each row is claimed exactly once. Elasticsearch is exempt from
`_claim` conformance entirely, because it carries neither tier. Its
document-versioning reports a lost race as a version conflict instead of a
graceful skip, so Elasticsearch is not a supported concurrent claim store.

The outbox epic had added generic conformance coverage under
`tests/repository/` (for `count`, `isnull`, `only`, `_delete_top`). We
consolidate that coverage into `tests/adapters/repository/generic/`, so a
single cross-adapter suite is the one source of truth and the `test-adapter`
runner reports on it. There is no second parallel set.

## Consequences

- Adapter authors get real conformance tests for the query-API primitives:
  `protean test test-adapter --provider=X` now exercises `count`, `only`,
  `isnull`, `lt`/`lte`, `_delete_top`, `F`, and `_claim` under the capability
  tiers the adapter declares.
- Memory-versus-SQL-versus-Elasticsearch divergence on these primitives fails a
  test rather than reaching production silently.
- The contract uses only the existing capability vocabulary. No new marker, no
  new taxonomy, nothing extra for an adapter author to learn.
- The cost is a documented semantic overload: `transactional` is doubling as the
  "in-memory + SQL, not Elasticsearch" selector for `F` even though `F` does
  not depend on transactions. If a future adapter supports transactions but not
  `F` (or the reverse), the `transactional` marker would misclassify it. The
  assignment would then need revisiting, most likely by giving `F` its own
  capability at that point.
- `_claim`'s concurrent test runs on SQLite as well as PostgreSQL/MSSQL. SQLite
  upholds no-double-claim by serializing writers. The test's contended workload
  is small, so serialization completes well within SQLite's busy timeout and
  the test is stable on SQLite.

## Alternatives Considered

**Add a separate mandatory/recommended/optional taxonomy.** An earlier framing
gave each primitive a tier label (mandatory, recommended, optional) independent
of the capability system. Rejected: it duplicates what the capability markers
already express. It also forces adapter authors to reconcile two overlapping
vocabularies.

**Add a dedicated capability flag for `F`** (for example `column_expressions`).
This would express `F` support honestly instead of overloading `transactional`.
Rejected for now: it adds a capability to the taxonomy for a single primitive.
It would also need a new `DatabaseCapabilities` flag added to every provider's
declaration. If `transactional` support and `F` support ever stop matching
across the adapters, this is the change to make.

**Normalize the return types of `_create`/`_update`/`_delete`.** These return
per-adapter model objects (the in-memory adapter returns a `dict`, SQLAlchemy
returns a model instance), so their `Any` return type is honestly correct.
Unifying the internal return contract is a separate refactor, out of scope for
a conformance-coverage change.
