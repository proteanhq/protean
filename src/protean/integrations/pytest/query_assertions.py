"""Pytest helpers that assert query shape and round-trip count.

These context managers hook SQLAlchemy's ``before_cursor_execute`` event to
observe the SQL a block issues, letting tests catch query-cost regressions
(extra round trips, subquery-wrapped counts, over-fetching) deterministically,
without timing-based benchmarks::

    from protean.integrations.pytest import assert_query_count

    def test_poll_issues_one_query(outbox_repo):
        with assert_query_count(1):
            outbox_repo.find_unprocessed(limit=10)

They are SQLAlchemy-specific. When the active provider is not SQLAlchemy-backed
(e.g. the in-memory adapter) there is no engine to observe, so the context
managers are **no-ops** and assert nothing. Mark tests that rely on them with
``@pytest.mark.database`` (or a specific backend marker) so they run against a
real SQL backend where the assertion is meaningful.

The engine is resolved from the active domain (``current_domain``) by default;
pass ``engine=`` explicitly for tests that manage their own domain or run
against a non-default provider.
"""

import re
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable, Iterator, List, Optional, Tuple

from protean.utils.globals import current_domain

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# ``sqlalchemy`` is an optional dependency. This module is re-exported from the
# auto-registered pytest plugin package, so it must import cleanly without it;
# the engine event API is imported lazily, only on the real-engine path.

# ``SELECT count(*) FROM (SELECT ... ) AS anon_1`` — a count wrapped around a
# full subquery, the pathology the outbox audit found behind ``.limit(1).all().total``.
SUBQUERY_WRAP_PATTERN = re.compile(
    r"SELECT\s+count\(\*\).*\bFROM\s*\(\s*SELECT\b",
    re.IGNORECASE | re.DOTALL,
)

# The token following ``LIMIT``: a literal integer, a named bind parameter
# (``%(name)s`` / ``:name``), or a positional placeholder (``?`` / ``%s``).
# SQLAlchemy renders LIMIT as a bound parameter on most dialects, so matching
# literals alone would miss real over-fetch.
LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+|%\(\w+\)s|:\w+|\?|%s)", re.IGNORECASE)
_NAMED_PARAM_PATTERN = re.compile(r"%\((\w+)\)s|:(\w+)")
_PLACEHOLDER_PATTERN = re.compile(r"\?|%s")

# Statements that count as a "query" (a data round trip). Connection setup such
# as ``PRAGMA``/``SET`` and transaction control (``BEGIN``/``COMMIT``) are
# excluded, so adapters that issue per-connection pragmas don't inflate counts.
_QUERY_VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")


def _is_query(statement: str) -> bool:
    return statement.lstrip().upper().startswith(_QUERY_VERBS)


def _limit_values(statement: str, parameters: Any) -> Iterator[int]:
    """Yield the integer LIMIT value(s) in a statement.

    Resolves bound parameters: named (``%(name)s`` / ``:name``) against a dict,
    positional (``?`` / ``%s``) by index against a sequence. A LIMIT whose value
    cannot be resolved to an ``int`` is skipped rather than guessed.
    """
    for match in LIMIT_PATTERN.finditer(statement):
        token = match.group(1)
        if token.isdigit():
            yield int(token)
            continue

        named = _NAMED_PARAM_PATTERN.fullmatch(token)
        if named is not None and isinstance(parameters, dict):
            value = parameters.get(named.group(1) or named.group(2))
            if isinstance(value, int):
                yield value
            continue

        if isinstance(parameters, (list, tuple)):
            # Positional: the value sits at the index equal to the number of
            # placeholders that precede this LIMIT token.
            index = len(_PLACEHOLDER_PATTERN.findall(statement[: match.start()]))
            if index < len(parameters) and isinstance(parameters[index], int):
                yield parameters[index]


def _resolve_engine(engine: "Optional[Engine]") -> "Optional[Engine]":
    """Resolve the SQLAlchemy engine to observe.

    Returns the explicit ``engine`` if given; otherwise the active domain's
    default provider engine. Returns ``None`` when no SQLAlchemy engine is
    available (e.g. the in-memory adapter or no domain bound), which makes the
    assertions no-ops. For a non-default provider, pass ``engine=`` explicitly.
    """
    if engine is not None:
        return engine

    try:
        providers = current_domain.providers
    except (RuntimeError, AttributeError):
        # No domain bound to the current context: the ``current_domain`` proxy
        # resolves to ``None`` (``AttributeError`` on ``.providers``) or raises
        # ``RuntimeError`` depending on the proxy implementation.
        return None

    default = providers.get("default")
    return getattr(default, "_engine", None) if default is not None else None


@contextmanager
def _listen(
    engine: "Optional[Engine]", callback: Callable[[str, Any], None]
) -> Iterator[None]:
    """Invoke ``callback(statement, parameters)`` for each query in the block.

    A ``None`` engine is a no-op (nothing to observe), so callers degrade
    cleanly on non-SQLAlchemy backends.
    """
    if engine is None:
        yield
        return

    # Imported here, not at module top, so the no-op path needs no SQLAlchemy.
    from sqlalchemy import event  # noqa: PLC0415

    def _before_cursor_execute(
        conn: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        many: bool,
    ) -> None:
        callback(statement, parameters)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


@contextmanager
def capture_queries(
    engine: "Optional[Engine]" = None,
) -> Iterator[List[Tuple[str, Any]]]:
    """Capture ``(statement, parameters)`` for each query in the block.

    Unlike the ``assert_*`` helpers, this makes no assertion of its own; it just
    yields the captured statements so a test can make a custom assertion — e.g.
    that a parent table's ``INSERT`` is emitted before a child table's. The list
    is empty and nothing is observed when no SQLAlchemy engine is resolved (the
    in-memory adapter or no domain bound), so callers must guard on it and mark
    the test ``@pytest.mark.database`` (or a backend marker) to run it where the
    assertion is meaningful.
    """
    resolved = _resolve_engine(engine)
    captured: List[Tuple[str, Any]] = []
    with _listen(
        resolved, lambda statement, params: captured.append((statement, params))
    ):
        yield captured


@contextmanager
def assert_query_count(
    expected: int, engine: "Optional[Engine]" = None
) -> Iterator[List[str]]:
    """Assert exactly ``expected`` queries are issued in the block.

    A "query" is a data round trip (``SELECT``/``INSERT``/``UPDATE``/``DELETE``/
    ``WITH``); connection setup (``PRAGMA``/``SET``) and transaction control are
    not counted, so adapters that issue per-connection pragmas don't inflate the
    count. Catches extra round trips: a ``count_by_status`` per-status loop, a
    1+N find-and-claim, etc. Yields the captured statements unfiltered (a test
    can inspect pragmas and transaction control too); the failure message lists
    only the counted queries. No-op when no SQLAlchemy engine is resolved.
    """
    resolved = _resolve_engine(engine)
    statements: List[str] = []
    with _listen(resolved, lambda statement, _params: statements.append(statement)):
        yield statements

    if resolved is None:
        return

    queries = [s for s in statements if _is_query(s)]
    actual = len(queries)
    if actual != expected:
        raise AssertionError(
            f"Expected {expected} quer{'y' if expected == 1 else 'ies'}, "
            f"got {actual}:\n" + _format_statements(queries)
        )


@contextmanager
def assert_no_subquery_wrap(
    engine: "Optional[Engine]" = None,
) -> Iterator[List[str]]:
    """Fail if any query wraps a ``count`` around a subquery.

    Catches the ``SELECT count(*) FROM (SELECT ... ) AS anon_1`` shape that a
    naive ``.limit(1).all().total`` emits instead of a flat ``SELECT count(*)``.
    No-op when no SQLAlchemy engine is resolved.
    """
    resolved = _resolve_engine(engine)
    statements: List[str] = []
    with _listen(resolved, lambda statement, _params: statements.append(statement)):
        yield statements

    if resolved is None:
        return

    offenders = [s for s in statements if SUBQUERY_WRAP_PATTERN.search(s)]
    if offenders:
        raise AssertionError(
            f"{len(offenders)} subquery-wrapped count(s) detected:\n"
            + _format_statements(offenders)
        )


@contextmanager
def assert_no_overfetch(
    expected_returned: int,
    ratio: float = 1.5,
    engine: "Optional[Engine]" = None,
) -> Iterator[List[Tuple[str, Any]]]:
    """Fail if any ``LIMIT`` exceeds ``expected_returned * ratio``.

    Catches over-fetch patterns such as ``min(limit * 3, 1000)`` that pull far
    more rows than the caller needs. ``ratio`` is the tolerated headroom over
    the expected row count. Resolves LIMIT values whether rendered as literals
    or bound parameters. No-op when no SQLAlchemy engine is resolved.
    """
    resolved = _resolve_engine(engine)
    executions: List[Tuple[str, Any]] = []
    with _listen(
        resolved, lambda statement, params: executions.append((statement, params))
    ):
        yield executions

    if resolved is None:
        return

    threshold = expected_returned * ratio
    offenders = []
    for statement, parameters in executions:
        # Check every LIMIT in the statement, not just the first: an outer
        # over-fetch can sit behind a smaller inner-subquery limit.
        for limit in _limit_values(statement, parameters):
            if limit > threshold:
                offenders.append((statement, limit))

    if offenders:
        raise AssertionError(
            f"Over-fetch detected (expected <= {threshold:g} rows):\n"
            + "\n".join(f"  - LIMIT {limit}: {_trim(s)}" for s, limit in offenders)
        )


def _format_statements(statements: List[str]) -> str:
    return "\n".join(f"  {i + 1}. {_trim(s)}" for i, s in enumerate(statements))


def _trim(statement: str, length: int = 200) -> str:
    """Collapse whitespace and truncate a statement for readable assertions."""
    collapsed = " ".join(statement.split())
    return collapsed if len(collapsed) <= length else collapsed[:length] + " ..."
