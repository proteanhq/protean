# ADR-0023: Query API Conformance Contract and Capability Tiers

**Status:** Accepted

**Date:** July 2026

## Context

Epic #941 (outbox query-path remediation) added a set of query and
persistence-path primitives that hot-path consumers depend on:

- `QuerySet.count()` / `BaseDAO._count`: count without materializing entities.
- `QuerySet.only()`: project a subset of persisted fields into read-only
  `Record` objects.
- `isnull`, `lt`, `lte` lookups.
- `F`: compare two columns of the same row inside a lookup.
- `BaseDAO._delete_top`: bounded delete for batched cleanups.
- `BaseDAO._claim`: atomic find-and-claim for concurrent consumers (ADR-0013).

Each primitive shipped with tests against one or two adapters (in-memory plus a
SQL backend, or an adapter-specific file). That left two gaps. First, adapter
divergence was invisible: nothing asserted that the in-memory, SQLAlchemy, and
Elasticsearch backends agree on these primitives, so a backend could quietly
diverge (a missing lookup, a different empty-result shape) without a test going
red. Second, the adapter-author self-check tool, `protean test test-adapter
--provider=X`, collects tests only from `tests/adapters/repository/generic/`, and
that directory had no coverage of these primitives, so the capability report an
adapter author relies on said nothing about them.

Protean already has a capability-marker system for exactly this purpose. Each
database provider declares the capabilities it supports (`basic_storage`,
`transactional`, `atomic_transactions`, `raw_queries`, `schema_management`,
`native_json`, `native_array`); each generic test is tagged with the capability
it needs; the runner selects the tests a given provider must pass. The question
this ADR settles is how the new query-API primitives map onto that system: which
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

**`F` sits at the `transactional` tier, not `basic_storage`.** The Elasticsearch
adapter raises `NotImplementedError` for `F`-bearing predicates by design:
column-to-column comparison there needs a Painless script query, which is not
implemented, so the adapter fails loudly rather than diverging silently. `F` is
therefore supported by exactly the in-memory and SQL backends. Those are also
exactly the adapters that carry the `transactional` capability (Elasticsearch
does not), so `transactional` is the marker that selects "in-memory + SQL, not
Elasticsearch." The alignment is by coincidence of the current adapter set, not
because `F` needs transactions; the marker is being used as the available
"not-Elasticsearch, real-store" selector. This is the same mechanism already
used to gate `_claim` correctness. Elasticsearch's loud-fail contract for `F` is
covered separately by an adapter-specific test, so the full contract (works on
in-memory + SQL, fails loudly on Elasticsearch) remains verified.

**`_claim` follows ADR-0013 and is split across two tiers.** Single-worker
correctness (claimed rows returned in post-claim state, `limit`/`order_by`
honoured, durability, no re-claim of already-claimed rows) is verified at the
`transactional` tier on in-memory and SQL. No-double-claim under concurrent
workers requires real database-level atomicity, so it is verified at the
`atomic_transactions` tier, which SQL backends carry and the in-memory store
does not. Relational backends uphold no-double-claim by one of three mechanisms:
`FOR UPDATE SKIP LOCKED` (the PostgreSQL fast path), serialized writers (SQLite),
or the portable guarded `UPDATE ... WHERE` re-evaluated under row-lock contention
(MSSQL), so each row is claimed exactly once. Elasticsearch is exempt from
`_claim` conformance
entirely: it carries neither tier, and its document-versioning surfaces a lost
race as a version conflict rather than a graceful skip, so it is not a supported
concurrent claim store.

The generic conformance coverage that the outbox epic had added under
`tests/repository/` (for `count`, `isnull`, `only`, `_delete_top`) is
consolidated into `tests/adapters/repository/generic/` so a single cross-adapter
suite is the one source of truth and the `test-adapter` runner reports on it.
There is no second parallel set.

## Consequences

- Adapter authors get a real conformance signal for the query-API primitives:
  `protean test test-adapter --provider=X` now exercises `count`, `only`,
  `isnull`, `lt`/`lte`, `_delete_top`, `F`, and `_claim` under the capability
  tiers the adapter declares.
- Memory-versus-SQL-versus-Elasticsearch divergence on these primitives fails a
  test rather than reaching production silently.
- The contract stays inside the existing capability vocabulary. No new marker,
  no new taxonomy, nothing extra for an adapter author to learn.
- The cost is a documented semantic overload: `transactional` is doubling as the
  "in-memory + SQL, not Elasticsearch" selector for `F` even though `F` does not
  depend on transactions. If a future adapter supports transactions but not `F`
  (or the reverse), this marker would misclassify it and the assignment would
  need revisiting (most likely by giving `F` its own capability at that point).
- `_claim`'s concurrent test runs on SQLite as well as PostgreSQL/MSSQL. SQLite
  upholds no-double-claim by serializing writers; for the small contended
  workload the test uses, serialization completes well within SQLite's busy
  timeout, so the test is stable there.

## Alternatives Considered

**A separate mandatory/recommended/optional taxonomy.** An earlier framing gave
each primitive a tier label (mandatory, recommended, optional) independent of the
capability system. Rejected: it duplicates what the capability markers already
express and forces adapter authors to reconcile two overlapping vocabularies.

**A dedicated capability flag for `F`** (for example `column_expressions`). This
would express `F` support honestly instead of overloading `transactional`.
Rejected for now: it grows the capability taxonomy for a single primitive, and it
would need a new `DatabaseCapabilities` flag threaded through every provider's
declaration. If the coincidental alignment between `transactional` and `F`
support ever breaks, this is the change to make.

**Return-type normalization of `_create`/`_update`/`_delete`.** These return
per-adapter model objects (the in-memory adapter returns a `dict`, SQLAlchemy
returns a model instance), so their `Any` return type is honestly correct.
Unifying the internal return contract is a separate refactor, out of scope for a
conformance-coverage change.
