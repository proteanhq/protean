"""Adapter parity: identical randomized histories agree across adapters
(:issue:`#1270`).

The same generated history is replayed against two adapters and their observable
outcomes are diffed. A divergence is a failing test Hypothesis shrinks to a
minimal reproduction. Covers the same adapters as the ``transactional``
conformance tier:

* **core suite** (Docker-free) — Memory vs SQLite.
* **FULL leg** — Memory vs PostgreSQL, where a real MVCC backend makes the
  parity assertion strongest.

Because a differential harness is blind to a bug both adapters share, three
things guard against a vacuous pass: the two seeded-divergence tests plant a real
Memory-vs-SQL disagreement on each observation channel and prove it is caught,
and the pin test asserts the *correct* adapter's exception classes directly (a
shared regression that stopped raising them would still pass the diff).

The harness itself lives in ``tests/verification/differential.py``, alongside the
:issue:`#1251` property suite.
"""

import pytest
from hypothesis import find, given
from hypothesis import settings as hypothesis_settings

from protean.exceptions import ExpectedVersionError, ObjectNotFoundError
from tests.shared import POSTGRES_URI
from tests.verification.differential import (
    Add,
    ConcurrentUpdate,
    Query,
    Read,
    Update,
    _exc_class_tag,
    build_parity_domain,
    diff_observations,
    format_divergences,
    histories,
    parity_settings,
    run_history,
)

pytestmark = pytest.mark.no_test_domain

# Derived through the harness' own tagging function so a pin can never drift from
# what the harness actually records for these exception classes.
_EXPECTED_VERSION_ERROR = _exc_class_tag(ExpectedVersionError)
_OBJECT_NOT_FOUND_ERROR = _exc_class_tag(ObjectNotFoundError)

# Built once per module: constructing a domain, repository, and tables per
# Hypothesis example would dominate runtime. ``run_history`` resets each provider
# before it replays, so reuse across examples is clean.
_memory_domain, _memory_repo = build_parity_domain({"provider": "memory"})
_sqlite_domain, _sqlite_repo = build_parity_domain(
    {"provider": "sqlite", "database_uri": "sqlite:///:memory:"}
)
_lost_update_domain, _lost_update_repo = build_parity_domain(
    {"provider": "memory"}, bug="lost_update"
)
_dropped_balance_domain, _dropped_balance_repo = build_parity_domain(
    {"provider": "memory"}, bug="dropped_balance"
)


@parity_settings
@given(history=histories())
def test_memory_and_sqlite_agree(history):
    memory = run_history(_memory_domain, _memory_repo, history)
    sqlite = run_history(_sqlite_domain, _sqlite_repo, history)

    divergences = diff_observations(memory, sqlite)
    assert not divergences, format_divergences(history, divergences)


def test_correct_sqlite_pins_expected_exception_classes():
    """Pin the *correct* adapter's exception classes, not just cross-adapter
    agreement. Differential agreement is blind to a shared regression: if both
    adapters stopped raising ``ExpectedVersionError`` on a stale write or
    ``ObjectNotFoundError`` on an absent read, the parity test would still pass.
    These assertions fail on that regression."""
    stale = run_history(
        _sqlite_domain,
        _sqlite_repo,
        [Add("id0", "seed", 0), ConcurrentUpdate("id0", 1, 2)],
    )
    # The concurrent op's 'second' slot is the outcome of the stale second write.
    assert stale[1][-1] == _EXPECTED_VERSION_ERROR, stale[1]

    missing = run_history(_sqlite_domain, _sqlite_repo, [Read("absent")])
    assert missing[0][-1] == _OBJECT_NOT_FOUND_ERROR, missing[0]


def test_seeded_lost_update_divergence_is_caught_and_shrunk():
    """A planted lost-update Memory adapter must fail the harness against SQL.

    Uses ``hypothesis.find`` to search for a diverging history and shrink it to a
    minimal reproduction. Only a concurrent update can expose last-write-wins, so
    the minimal counterexample must contain one; if the harness were vacuous
    ``find`` would raise ``NoSuchExample`` and fail the test instead.
    """

    def diverges(history) -> bool:
        sqlite = run_history(_sqlite_domain, _sqlite_repo, history)
        buggy = run_history(_lost_update_domain, _lost_update_repo, history)
        return bool(diff_observations(sqlite, buggy))

    minimal = find(histories(), diverges, settings=parity_settings)

    # Only a concurrent update can expose last-write-wins, so the shrunk
    # reproduction must contain one. (The exact shrunk length is a property of
    # Hypothesis' shrinker and varies by profile — e.g. CI's ``derandomize`` —
    # so it is deliberately not asserted.)
    assert any(isinstance(op, ConcurrentUpdate) for op in minimal), minimal
    # And the race is the *cause*: with every concurrent update removed, the two
    # adapters agree again — nothing else in the reproduction drives the divergence.
    without_race = [op for op in minimal if not isinstance(op, ConcurrentUpdate)]
    assert not diverges(without_race), without_race


def test_seeded_lost_update_is_not_vacuous_on_a_fixed_history():
    """A direct guard, independent of Hypothesis search: a hand-built concurrent
    update diverges between the correct SQL adapter and the lost-update Memory
    adapter, and the divergence carries the behavior (the SQL side raised
    ``ExpectedVersionError``; the buggy side silently kept a version). If this
    ever agrees, the seed stopped planting a divergence and the shrinking test
    above would pass vacuously."""
    history = [Add("id0", "seed", 0), ConcurrentUpdate("id0", 1, 2)]

    sqlite = run_history(_sqlite_domain, _sqlite_repo, history)
    buggy = run_history(_lost_update_domain, _lost_update_repo, history)

    divergences = diff_observations(sqlite, buggy)
    # The concurrent op (position 1) is where the OCC divergence shows: the SQL
    # side records the OCC error, the buggy side a surviving version number.
    concurrent = next(d for d in divergences if d[0] == 1)
    sqlite_obs, buggy_obs = concurrent[1], concurrent[2]
    assert sqlite_obs[-1] == _EXPECTED_VERSION_ERROR, sqlite_obs
    assert buggy_obs[-1] != _EXPECTED_VERSION_ERROR, buggy_obs


def test_seeded_dropped_balance_divergence_is_caught_on_read_query_and_snapshot():
    """The lost-update seed exercises only the concurrency / exception channel.
    This one plants a data-corruption bug (balance zeroed on write) and proves the
    read, query, and final-snapshot channels are non-vacuous too: with a stored
    balance the correct adapter and the corrupt one must disagree on the read
    result, the filtered query result, and the end-state snapshot."""
    history = [Add("id0", "seed", 5), Read("id0"), Query(3)]

    sqlite = run_history(_sqlite_domain, _sqlite_repo, history)
    corrupt = run_history(_dropped_balance_domain, _dropped_balance_repo, history)

    divergences = diff_observations(sqlite, corrupt)
    kinds = {d[1][1] for d in divergences if isinstance(d[0], int)}
    assert "read" in kinds, divergences  # Read(id0): balance 5 vs 0
    assert "query" in kinds, divergences  # Query(3): id0 matches vs not
    assert any(d[0] == "final" or d[1][0] == "final" for d in divergences), divergences


def test_diff_observations_reports_positions_and_length_mismatch():
    """Unit-level contract for the differ: it flags each disagreeing position and
    a trailing length mismatch when one adapter produced fewer observations (e.g.
    a history that aborted early on one side)."""
    assert diff_observations([("a", 1)], [("a", 1)]) == []

    position = diff_observations([("a", 1)], [("a", 2)])
    assert position == [(0, ("a", 1), ("a", 2))]

    length = diff_observations([("a", 1), ("b", 2)], [("a", 1)])
    assert ("length", 2, 1) in length


def test_run_history_records_an_unexpected_raise_as_an_observation():
    """An operation the generator would never emit (here, an update to an absent
    id) still yields a recorded ``("raised", <class>)`` observation instead of
    crashing the replay, so a divergence where only one adapter raises would be
    diffed order-independently rather than aborting whichever adapter ran first."""
    observations = run_history(_sqlite_domain, _sqlite_repo, [Update("ghost", 5)])

    assert observations[0] == (0, "raised", _OBJECT_NOT_FOUND_ERROR), observations


# --- FULL leg: Memory vs PostgreSQL ---------------------------------------

# PostgreSQL replays a real MVCC backend, so the per-example budget is smaller
# than the in-process SQLite comparison to keep the FULL leg's runtime sane.
pg_parity_settings = hypothesis_settings(parity_settings, max_examples=40)


@pytest.fixture(scope="module")
def postgresql_parity():
    """The module-level Memory domain paired with a PostgreSQL one, tables dropped
    and the engine closed on teardown."""
    pg_domain, pg_repo = build_parity_domain(
        {"provider": "postgresql", "database_uri": POSTGRES_URI}
    )
    provider = pg_domain.providers["default"]
    try:
        yield pg_domain, pg_repo
    finally:
        # close() runs even if the drop raises, so the engine never leaks.
        try:
            with pg_domain.domain_context():
                provider._drop_database_artifacts()
        finally:
            provider.close()


@pytest.mark.postgresql
def test_memory_and_postgresql_agree(postgresql_parity):
    pg_domain, pg_repo = postgresql_parity

    @pg_parity_settings
    @given(history=histories())
    def _property(history):
        memory = run_history(_memory_domain, _memory_repo, history)
        postgresql = run_history(pg_domain, pg_repo, history)

        divergences = diff_observations(memory, postgresql)
        assert not divergences, format_divergences(history, divergences)

    _property()
