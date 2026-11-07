# UNINDEXED_FILTER_PATH

| | |
|---|---|
| **Code** | `UNINDEXED_FILTER_PATH` |
| **Category** | `persistence` |
| **Level** | `warning` |

## What it flags

An aggregate field that a repository query **filters on** but that **no declared
index covers**. Such a query is a full table scan on a relational backend: the
cost is invisible on small development data and grows with the production table.

`protean check` reads two halves and joins them:

- the **declared-index** half, the indexes declared on the aggregate, from the
  IR, and
- the **filter-path** half. The fields each repository query names, read from
  method bodies through the behavioral-analysis substrate.

It reports one finding per uncovered field per call-site: the same field
filtered in two methods yields two findings, each pointing at its own query.

A query is a call to one of the repository read surfaces (`filter`, `get`,
`find`, `find_by`, `exclude`). The rule counts the call when its receiver
statically resolves to a registered repository or aggregate class, or is
self-rooted (`self._dao`) inside a repository. The finding is attributed to the
**aggregate** (that is where the `Index()` fix and the natural suppression site
live), names the field, and points at the call-site as
`<element>.<method>, line N`, the enclosing element and source
line, stable across machines so it does not pollute the content-checksummed IR
(the absolute source path is deliberately left out).

An operator lookup such as `age__gte`, `status__in`, or `email__contains`
filters its base field. The rule strips the `__<lookup>` suffix and evaluates
the base (`age`, `status`, `email`), so it flags an operator query on an
unindexed column and passes one on an indexed column.

## When a field is covered

A filtered field is **not** flagged when:

- it is the aggregate's **identifier**, a relational backend indexes the
  primary key;
- it carries a single-column **`unique=True`** constraint. A unique constraint
  is a real index on a relational backend; or
- it is the **leading column** of a declared `Index`.

Only the *leading* column of a composite index is covered. A filter on a
non-leading column alone (for example `Index("channel", "region")` with a filter
on `region`) is **flagged**, because that index cannot serve it.

## Scope and limits

The rule is deterministic and conservative: when it cannot resolve a query to a
specific aggregate, it **skips the query and does not guess**. An unresolved
join is a silent miss and never a false positive. It deliberately does **not**
cover:

- **Dynamic filters**: `filter(**kwargs)` names no field, so it is skipped.
- **Unresolvable receivers**: The rule skips a `.filter(...)` on a receiver
  that static analysis cannot match to a registered class. Examples are a plain
  local variable or parameter, and the idiomatic
  `current_domain.repository_for(Order).filter(...)`, whose receiver is a call
  result. The rule joins a query only when its receiver resolves to a
  repository or aggregate **class** (`OrderRepository.filter(...)`,
  `Order.filter(...)`) or the query is a self-rooted repository query. Instance
  and `repository_for(...)` receivers need dataflow analysis, which the rule
  does not do yet.
- **Non-scalar names**: The rule skips a filter that names a value-object
  attribute, an association, or any other name that is not a declared scalar
  field of the aggregate. The other persistence rules use the same scalar-field
  scope.
- **Abstract aggregates**: A non-instantiable base emits no table, so a filter
  path joined to one is not flagged.

## Why it matters

A query that filters on an unindexed column forces the database to scan the
whole table. On a development database of a few hundred rows this is
instantaneous and invisible; in production, against millions of rows, the same
query degrades linearly with table size. Tests never reveal the missing index,
so the slow query typically first appears as a production incident. This rule
detects it mechanically, at build time, from the code as written.

## Example

Flagged, a repository filters on a field the aggregate does not index:

```python
--8<-- "concepts/protean-check/rules/unindexed-filter-path/001.py:flagged"
```

Compliant. The filtered field is indexed:

```python
--8<-- "concepts/protean-check/rules/unindexed-filter-path/002.py:compliant"
```

## How to fix

- Add an index led by the field to the aggregate
  (`indexes=[Index("reference")]`, or a composite index whose **leading** column
  is this field), or
- suppress the check when the scan cost does not matter, as for a small lookup
   table or a one-off admin/reporting query.

## Suppressing

Suppress the rule for a single aggregate with `suppress_checks` (it resolves
against the aggregate FQN the finding is attributed to):

```python
--8<-- "concepts/protean-check/rules/unindexed-filter-path/003.py:suppressed"
```

Or grandfather a fixed number of existing findings while adopting the rule, via
the `[lint]` table:

```toml
[lint.suppressions]
UNINDEXED_FILTER_PATH = 12   # allow the first 12 findings, fail on the 13th
```
