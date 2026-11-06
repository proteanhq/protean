# Test Query Shape

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Functional tests confirm a query returns the right rows, but they say nothing
about how expensive it was. A query can return correct results while issuing an
extra round trip per row, wrapping a count in a subquery, or fetching three
times more rows than it needs. On small test datasets you do not see these
problems. In production, the same problems can stall a queue that would
otherwise stay healthy.

Protean ships three pytest context managers that assert query *shape* and
*round-trip count*. With them, a cost regression fails at PR time instead of in
production. A fourth, `capture_queries`, yields the raw statements for custom
assertions the three do not cover (such as INSERT ordering):

```python
# fragment
--8<-- "guides/testing/query-shape-tests/001.py:imports"
```

## When to use these

Use query-shape assertions on the hot read paths, where cost matters: poll
loops, claim-and-process paths, dashboards, and any repository method under
load. They complement functional tests rather than replace them: assert *what*
a query returns with ordinary assertions, and *how* it runs with these.

They are SQLAlchemy-specific. When the active provider is the in-memory
adapter, the context managers have no engine to observe. On that adapter they
are no-ops and assert nothing. Mark tests that use them with
`@pytest.mark.database` (or a specific backend marker) so they run against a
real SQL backend where the assertion is meaningful. Protean's pytest plugin
does not register `database`. Register it in your `conftest.py`, as the
fixtures below do, or pytest warns about an unknown mark.

The examples on this page run against SQLite, with this domain and these
fixtures:

??? example "The domain and fixtures under test"

    ```python
    # fragment
    --8<-- "guides/testing/query-shape-tests/ticketing/__init__.py:domain"
    ```

    ```python
    # fragment
    --8<-- "guides/testing/query-shape-tests/conftest.py:conftest"
    ```

## `assert_query_count`

Asserts an exact number of queries (data round trips) are issued in the block.
Catches N+1 patterns and accidental extra round trips:

```python
# fragment
--8<-- "guides/testing/query-shape-tests/001.py:query_count"
```

A "query" is a `SELECT`, `INSERT`, `UPDATE`, `DELETE`, or `WITH` statement.
Connection setup (such as a `PRAGMA` or `SET`) and transaction control
(`BEGIN`/`COMMIT`) are not counted. As a result, adapters that issue
per-connection pragmas do not inflate the number. The context manager yields
the captured statements, so a failing assertion prints exactly what ran.

## `assert_no_subquery_wrap`

Fails if any query wraps a count around a subquery, the
`SELECT count(*) FROM (SELECT ... ) AS anon_1` shape, where a flat
`SELECT count(*)` would do. The first test guards a repository count against
that regression. The second issues a wrapped count on purpose and shows the
assertion catches it:

```python
# fragment
--8<-- "guides/testing/query-shape-tests/001.py:subquery_wrap"
```

## `assert_no_overfetch`

Fails if any `LIMIT` exceeds the number of rows needed by the caller. Pass the
expected row count. The assertion allows headroom through `ratio` (default
`1.5`):

```python
# fragment
--8<-- "guides/testing/query-shape-tests/001.py:overfetch"
```

A `LIMIT 10` passes (`10 <= 10 * 1.5`); a `min(limit * 3, 1000)` over-fetch
that emits `LIMIT 30` fails. When a path legitimately reads a small multiple of
its returned rows, widen `ratio`.

## `capture_queries`

When the three assertions above do not fit, use `capture_queries`. It yields
the raw statements from a block for your own custom assertion. It powers, for
example, an insert-ordering check that a parent row is written before its
children:

```python
# fragment
--8<-- "guides/testing/query-shape-tests/001.py:capture_queries"
```

`capture_queries` yields a list of `(statement, parameters)` tuples. Like the
assertions above, it is a no-op on the in-memory adapter, which has no engine
to observe. On that adapter the list is empty. Guard on that: on a real backend
an empty capture means the hook never fired, so assert the list is non-empty
before trusting an ordering check.

## Engine resolution

By default the engine is resolved from the active domain's **default**
provider. For tests that set up their own domain or target a non-default
provider, pass the engine explicitly:

```python
# fragment
--8<-- "guides/testing/query-shape-tests/001.py:explicit_engine"
```

## Avoiding false positives

- **Scope the block tightly**: Only wrap the call under test. Keep seeding,
  fixture setup, and assertions that run their own queries outside the block.
- **Count only the queries the operation issues**: A `.all()` with the default
  `with_total=True` issues a second `COUNT` query. When you mean to assert a
  single round trip, use `with_total=False`.
- **These are deterministic, not statistical**: They catch shape regressions,
  not latency. For timing-based regression detection, use a benchmark instead.
