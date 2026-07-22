# QuerySet

Chainable query builder for repository data access. QuerySets support
filtering, excluding, ordering, pagination, and lookup operations.

See [Retrieve Aggregates guide](../guides/change-state/retrieve-aggregates.md)
for practical usage.

::: protean.core.queryset.QuerySet
    options:
      show_root_heading: false
      inherited_members: false

---

## Record

The read-only value type returned by [`QuerySet.only()`](#protean.core.queryset.QuerySet.only).
A `Record` carries a projected subset of a single result's fields. It is not a
domain entity: it has no behavior, runs no invariants, and cannot be persisted.

::: protean.core.queryset.Record
    options:
      show_root_heading: false
      inherited_members: false

---

## F

A reference to another column of the same row, for use as the right-hand side
of a lookup inside `filter()`/`Q` (e.g. `filter(retry_count__lt=F("max_retries"))`).
Resolved natively by the in-memory and SQLAlchemy adapters; the Elasticsearch
adapter raises `NotImplementedError` for `F`-bearing predicates. See the
[Retrieve Aggregates guide](../guides/change-state/retrieve-aggregates.md#comparing-two-fields-with-f)
for usage.

::: protean.utils.query.F
    options:
      show_root_heading: false
      inherited_members: false

---

## Cross-adapter conformance

Every built-in adapter is held to the same behaviour for these query-API
primitives through the [conformance test suite](../reference/testing/conformance.md).
Each primitive is gated by a capability tier: an adapter that declares a
capability must pass every conformance test tagged with it. See
[ADR-0023](https://github.com/proteanhq/protean/blob/main/docs/adr/0023-query-api-conformance-contract-and-capability-tiers.md)
for the rationale.

| Primitive | Capability tier | Adapters that must pass |
|---|---|---|
| `count()` | `basic_storage` | all (including Elasticsearch) |
| `only()` projection | `basic_storage` | all |
| `isnull` lookup | `basic_storage` | all |
| `lt` / `lte` lookups | `basic_storage` | all |
| `_delete_top` bounded delete | `basic_storage` | all |
| `F()` column comparison | `transactional` | in-memory + SQL |
| `_claim` correctness | `transactional` | in-memory + SQL |
| `_claim` no-double-claim (concurrent) | `atomic_transactions` | SQL only |

`F()` and `_claim` are gated above `basic_storage` because Elasticsearch does not
support them: it raises `NotImplementedError` for `F`-bearing predicates, and its
document-versioning makes it unsuitable as a concurrent claim store.
