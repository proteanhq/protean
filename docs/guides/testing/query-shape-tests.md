# Test Query Shape

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Functional tests confirm a query returns the right rows, but they say nothing
about how expensive it was. A query can return correct results while issuing an
extra round trip per row, wrapping a count in a subquery, or fetching three
times more rows than it needs. On small test datasets these pathologies are
invisible; in production they are the difference between a healthy queue and a
stalled one.

Protean ships three pytest context managers that assert query *shape* and
*round-trip count*, so a cost regression fails at PR time instead of in
production. A fourth, `capture_queries`, yields the raw statements for custom
assertions the three do not cover (such as INSERT ordering):

```python
from protean.integrations.pytest import (
    assert_query_count,
    assert_no_subquery_wrap,
    assert_no_overfetch,
    capture_queries,
)
```

## When to use these

Reach for query-shape assertions on hot read paths where cost matters: poll
loops, claim-and-process paths, dashboards, and any repository method that runs
under load. They complement functional tests rather than replace them: assert
*what* a query returns with ordinary assertions, and *how* it runs with these.

They are SQLAlchemy-specific. When the active provider is the in-memory adapter
there is no engine to observe, so the context managers are no-ops and assert
nothing. Mark tests that use them with `@pytest.mark.database` (or a specific
backend marker) so they run against a real SQL backend where the assertion is
meaningful.

## `assert_query_count`

Asserts an exact number of queries (data round trips) are issued in the block.
Catches N+1 patterns and accidental extra round trips:

```python
import pytest
from protean.integrations.pytest import assert_query_count


@pytest.mark.database
def test_poll_issues_a_single_query(outbox_repo):
    with assert_query_count(1):
        outbox_repo.find_unprocessed(limit=10)
```

A "query" is a `SELECT`, `INSERT`, `UPDATE`, `DELETE`, or `WITH` statement.
Connection setup (such as a `PRAGMA` or `SET`) and transaction control
(`BEGIN`/`COMMIT`) are not counted, so adapters that issue per-connection
pragmas do not inflate the number. The context manager yields the captured
statements, so a failing assertion prints exactly what ran.

## `assert_no_subquery_wrap`

Fails if any query wraps a count around a subquery, the
`SELECT count(*) FROM (SELECT ... ) AS anon_1` shape that a naive
`.limit(1).all().total` emits instead of a flat `SELECT count(*)`:

```python
@pytest.mark.database
def test_count_uses_a_flat_count(outbox_repo):
    with assert_no_subquery_wrap():
        outbox_repo.count_by_status()
```

## `assert_no_overfetch`

Fails if any `LIMIT` exceeds the rows the caller actually needs. Pass the
expected row count; the assertion allows headroom via `ratio` (default `1.5`):

```python
@pytest.mark.database
def test_poll_does_not_overfetch(outbox_repo, seeded_outbox):
    with assert_no_overfetch(expected_returned=10):
        outbox_repo.find_unprocessed(limit=10)
```

A `LIMIT 10` passes (`10 <= 10 * 1.5`); a `min(limit * 3, 1000)` over-fetch that
emits `LIMIT 30` fails. Widen `ratio` when a path legitimately reads a small
multiple of what it returns.

## `capture_queries`

When the three assertions above do not fit, `capture_queries` yields the raw
statements a block issues so you can write a custom assertion. It powers, for
example, an insert-ordering check that a parent row is written before its
children:

```python
import re
import pytest
from protean.integrations.pytest import capture_queries


@pytest.mark.database
def test_parent_inserted_before_children(order_repo, order):
    with capture_queries() as captured:
        order_repo.add(order)

    tables = [
        re.search(r"INSERT INTO (\w+)", statement, re.IGNORECASE).group(1).lower()
        for statement, _params in captured
        if statement.lstrip().upper().startswith("INSERT")
    ]
    assert tables, "no INSERTs captured; the hook did not fire"
    assert tables.index("order") < tables.index("order_item")
```

`capture_queries` yields a list of `(statement, parameters)` tuples. Like the
assertions above it is a no-op on the in-memory adapter, where there is no engine
to observe, so the list is empty. Guard on that: on a real backend an empty
capture means the hook never fired, so assert the list is non-empty before
trusting an ordering check.

## Engine resolution

By default the engine is resolved from the active domain's **default**
provider. For tests that manage their own domain or target a non-default
provider, pass the engine explicitly:

```python
with assert_query_count(1, engine=my_engine):
    ...
```

## Avoiding false positives

- **Scope the block tightly.** Only wrap the call under test. Seeding, fixture
  setup, and assertions that themselves query should sit outside the block.
- **Count what the operation issues, not the framework.** A `.all()` with the
  default `with_total=True` issues a second `COUNT` query; use
  `with_total=False` when you mean to assert a single round trip.
- **These are deterministic, not statistical.** They catch shape regressions,
  not latency. For timing-based regression detection, use a benchmark instead.
