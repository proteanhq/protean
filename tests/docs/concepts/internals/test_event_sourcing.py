"""Run the examples on ``docs/concepts/internals/event-sourcing.md``.

``001.py`` is an event-sourced ``Order`` built by a ``place`` factory on
``_create_new()``. ``002.py`` registers two users (one changes her email) and
places one order, then takes manual snapshots. ``003.py`` keeps a ``Balances``
projection from ``User`` and ``Transaction`` events, then rebuilds it.
"""

import pytest

from protean.exceptions import IncorrectUsageError
from protean.utils.projection_rebuilder import RebuildResult
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def ordering():
    example = load_example("concepts/internals/event-sourcing/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


# Live path: raise_() runs the @apply handler


def test_place_sets_state_through_the_apply_handler(ordering):
    order = ordering.Order.place("Alice")

    assert order.customer_name == "Alice"
    assert order.status == "PLACED"
    assert order._version == 0
    assert [type(event) for event in order._events] == [ordering.OrderPlaced]
    assert order._events[0].order_id == str(order.id)


def test_each_raised_event_increments_the_version_once(ordering):
    order = ordering.Order.place("Alice")
    order.confirm()

    assert order.status == "CONFIRMED"
    assert order._version == 1


# Replay path: from_events() runs the same @apply handlers


def test_from_events_rebuilds_the_same_state(ordering):
    order = ordering.Order.place("Alice")
    order.confirm()

    rebuilt = ordering.Order.from_events(order._events)

    assert rebuilt.id == order.id
    assert rebuilt.customer_name == "Alice"
    assert rebuilt.status == "CONFIRMED"
    assert rebuilt._version == 1


def test_from_events_rejects_an_empty_list(ordering):
    with pytest.raises(IncorrectUsageError, match="from an empty event list"):
        ordering.Order.from_events([])


# Manual snapshots


@pytest.fixture
def accounts():
    example = load_example("concepts/internals/event-sourcing/002.py")
    with example.domain.domain_context():
        yield example


def snapshot_rows(example, aggregate_cls, identifier):
    category = aggregate_cls.meta_.stream_category
    return example.domain.event_store.store._read(f"{category}:snapshot-{identifier}")


def test_manual_snapshot_is_written_below_the_threshold(accounts):
    # user-id-123 has two events, far below the default threshold of 10.
    assert accounts.domain.config["snapshot_threshold"] == 10

    rows = snapshot_rows(accounts, accounts.User, "user-id-123")

    # create_snapshot, create_snapshots and create_all_snapshots each wrote one.
    assert len(rows) == 3
    assert {row["type"] for row in rows} == {"SNAPSHOT"}


def test_snapshot_holds_state_from_the_whole_stream(accounts):
    rows = snapshot_rows(accounts, accounts.User, "user-id-123")

    # The email comes from the second event, so the whole stream was replayed.
    assert {row["data"]["email"] for row in rows} == {"ann@work.example.com"}


def test_snapshot_calls_return_counts_per_aggregate(accounts):
    assert accounts.count == 2
    assert accounts.results == {"User": 2, "Order": 1}


# Projection rebuilding


@pytest.fixture
def banking(capsys):
    example = load_example("concepts/internals/event-sourcing/003.py")
    printed = capsys.readouterr().out.splitlines()
    with example.domain.domain_context():
        yield example, printed


def test_rebuild_reports_events_dispatched_and_skipped(banking):
    example, printed = banking

    assert printed == ["4 events, 0 skipped"]
    assert example.results == {
        "Balances": RebuildResult(
            projection_name="Balances",
            projectors_processed=1,
            categories_processed=2,
            events_dispatched=4,
            events_skipped=0,
            errors=[],
        )
    }


def test_rebuild_replays_across_categories_in_stored_order(banking):
    # Transacted events need the Balances row that Registered creates, so
    # the user and transaction streams must replay in global order.
    example, _ = banking
    repo = example.domain.repository_for(example.Balances)

    assert repo.get("u-1").balance == 70.0
    assert repo.get("u-2").balance == 0.0


def test_rebuild_replaces_stale_projection_data(banking):
    example, _ = banking
    repo = example.domain.repository_for(example.Balances)
    stale = repo.get("u-1")
    stale.balance = 999.0
    repo.add(stale)

    result = example.domain.rebuild_projection(example.Balances)

    assert result.success
    assert repo.get("u-1").balance == 70.0
