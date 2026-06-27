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
