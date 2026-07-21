# UNINDEXED_FILTER_PATH

| | |
|---|---|
| **Code** | `UNINDEXED_FILTER_PATH` |
| **Category** | `persistence` |
| **Level** | `warning` |

## What it flags

An aggregate field that a repository query **filters on** but that **no declared
index covers**. Such a query is a full table scan on every backend: the cost is
invisible on small development data and grows with the production table.

`protean check` reads two halves and joins them:

- the **declared-index** half — the indexes declared on the aggregate, from the
  IR, and
- the **filter-path** half — the fields each repository query names, read from
  method bodies through the behavioral-analysis substrate.

It reports one finding per uncovered field per call-site: the same field
filtered in two methods yields two findings, each pointing at its own query.

A query is any of the repository read surfaces — `filter`, `get`, `find`,
`find_by`, `exclude` — recognised on a repository receiver. The finding is
attributed to the **aggregate** (that is where the `Index()` fix and the natural
suppression site live), names the field, and points at the call-site
`path:line:col`.

## When a field is covered

A filtered field is **not** flagged when:

- it is the aggregate's **identifier** — every backend indexes the primary key;
- it carries a single-column **`unique=True`** constraint — a unique constraint
  is a real index on every backend; or
- it is the **leading column** of a declared `Index`.

Only the *leading* column of a composite index is covered. A filter on a
non-leading column alone (for example `Index("channel", "region")` with a filter
on `region`) is **flagged**, because that index cannot serve it.

## Scope and limits

The rule is deterministic and conservative: where it cannot resolve a query to a
specific aggregate, it **skips rather than guesses**, so an unresolved join is a
silent miss, never a false positive. It deliberately does **not** cover:

- **Dynamic filters.** `filter(**kwargs)` names no field, so it is skipped.
- **Unresolvable receivers.** A `.filter(...)` on a plain local variable or
  parameter (a receiver static analysis cannot tie to a repository) is skipped —
  it needs type information the check does not have.
- **Non-scalar names.** A filter naming a value-object attribute, an
  association, or a name that is not a declared scalar field of the aggregate is
  left alone (the same scalar-field scope as the sibling persistence rules).
- **Abstract aggregates.** A non-instantiable base emits no table, so a filter
  path joined to one is not flagged.

## Why it matters

A query that filters on an unindexed column forces the database to scan the
whole table. On a development database of a few hundred rows this is
instantaneous and invisible; in production, against millions of rows, the same
query degrades linearly with table size. Because the mismatch never shows up in
tests, it typically surfaces first as a production incident. This rule detects
it mechanically, at build time, from the code as written.

## Example

Flagged — a repository filters on a field the aggregate does not index:

```python
from protean import Domain, Index
from protean.core.repository import BaseRepository
from protean.fields import Identifier, String

domain = Domain(name="app")

@domain.aggregate(indexes=[Index("status")])
class Order:
    order_id = Identifier(identifier=True)
    status = String(max_length=20)
    reference = String(max_length=40)   # not indexed

@domain.repository(part_of=Order)
class OrderRepository:
    def by_reference(self, reference):
        # filters `reference`, which no index covers -> UNINDEXED_FILTER_PATH
        return self._dao.filter(reference=reference)

    def open(self):
        # filters `status`, the leading column of Index("status") -> no finding
        return self._dao.filter(status="open")
```

Compliant — the filtered field is indexed:

```python
@domain.aggregate(indexes=[Index("status"), Index("reference")])
class Order:
    order_id = Identifier(identifier=True)
    status = String(max_length=20)
    reference = String(max_length=40)   # now indexed -> no finding
```

## How to fix

- Add an index led by the field to the aggregate
  (`indexes=[Index("reference")]`, or a composite index whose **leading** column
  is this field), or
- suppress the check when the scan is acceptable — a small lookup table, or a
  one-off admin/reporting query where the cost does not matter.

## Suppressing

Suppress the rule for a single aggregate with `suppress_checks` (it resolves
against the aggregate FQN the finding is attributed to):

```python
@domain.aggregate(
    indexes=[Index("status")],
    suppress_checks=["UNINDEXED_FILTER_PATH"],
)
class Order:
    order_id = Identifier(identifier=True)
    status = String(max_length=20)
    reference = String(max_length=40)
```

Or grandfather a fixed number of existing findings while adopting the rule, via
the `[lint]` table:

```toml
[lint.suppressions]
UNINDEXED_FILTER_PATH = 12   # allow the first 12 findings, fail on the 13th
```
