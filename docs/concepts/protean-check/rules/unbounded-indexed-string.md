# UNBOUNDED_INDEXED_STRING

| | |
|---|---|
| **Code** | `UNBOUNDED_INDEXED_STRING` |
| **Category** | `persistence` |
| **Level** | `warning` |

## What it flags

An aggregate field that is **both** included in a declared index **and** an
unbounded string. `protean check` reports one finding per flagged field per
index occurrence.

A string field is *unbounded* when it carries no length bound:

- its type is `Text` (unbounded by construction), or
- its type is `String` declared with `String(max_length=None)`.

A normal `String()` defaults to `max_length=255` and is therefore bounded — it
is never flagged. Non-string fields (`Integer`, `Date`, and so on) are never
flagged.

## Why it matters

An index over a genuinely unbounded string is not portable across the engines
Protean supports:

| Engine | Behaviour on an unbounded indexed string |
|---|---|
| SQL Server | **Rejects** the index — a key column cannot exceed the maximum key length, and an unbounded (`nvarchar(max)`) column cannot participate in a key. |
| MySQL | Requires an **explicit prefix length** (`INDEX (col(191))`); without one the DDL fails, and a prefix silently indexes only a leading slice of the value. |
| PostgreSQL | Accepts it, but with **storage and performance overhead** — large values bloat the index and can exceed the B-tree row-size limit at runtime. |

Epic #941 set `max_length` on the Outbox string fields for exactly this reason:
indexes cannot be created on unbounded strings on most engines. This rule
detects the same mismatch mechanically, at build time, for every aggregate.

## Example

Flagged — an unbounded `Text` field is indexed:

```python
from protean import Domain, Index
from protean.fields import Text

domain = Domain(name="app")

@domain.aggregate(indexes=[Index("body")])
class Note:
    body = Text()          # unbounded; indexed -> UNBOUNDED_INDEXED_STRING
```

Compliant — a bounded `String` field is indexed, and the unbounded field is
left out of every index:

```python
from protean.fields import String, Text

@domain.aggregate(indexes=[Index("slug")])
class Article:
    slug = String(max_length=120)   # bounded; indexed -> no finding
    body = Text()                   # unbounded but not indexed -> no finding
```

## How to fix

- Give the field a bounded length (`String(max_length=N)`) sized to its domain,
  or
- remove it from the index if it does not need to be indexed.

## Suppressing

Suppress the rule for a single aggregate with `suppress_checks`:

```python
@domain.aggregate(
    indexes=[Index("body")],
    suppress_checks=["UNBOUNDED_INDEXED_STRING"],
)
class Note:
    body = Text()
```
