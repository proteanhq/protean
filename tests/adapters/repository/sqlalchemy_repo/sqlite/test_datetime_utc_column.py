"""SQLite stores a ``DateTime`` field as UTC and loads it UTC-aware.

Each lookup case stores one ``Slot`` at 12:00 UTC and filters it with a value
that carries a different UTC offset, or no offset at all.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.schema import CreateTable

from protean.adapters.repository.sqlalchemy import UTCDateTime
from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, String

pytestmark = pytest.mark.sqlite

PLUS_TWO = timezone(timedelta(hours=2))
MINUS_TWO = timezone(timedelta(hours=-2))

STORED = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
# 11:00 UTC, written with a later wall-clock time than the stored value.
EARLIER = datetime(2026, 10, 20, 13, 0, tzinfo=PLUS_TWO)
# 13:00 UTC, written with an earlier wall-clock time than the stored value.
LATER = datetime(2026, 10, 20, 11, 0, tzinfo=MINUS_TWO)
# 12:00 UTC, the stored instant written with a different offset.
SAME_INSTANT = datetime(2026, 10, 20, 14, 0, tzinfo=PLUS_TWO)


class Slot(BaseAggregate):
    name = String(max_length=50)
    at = DateTime()


@pytest.fixture
def repo(test_domain):
    test_domain.register(Slot)
    test_domain.init(traverse=False)
    provider = test_domain.providers["default"]
    repo = test_domain.repository_for(Slot)
    table = repo._dao.database_model_cls.__table__
    # The test database is a file, so a table left by an earlier run would
    # hide the column types this run builds.
    table.drop(provider._engine, checkfirst=True)
    table.create(provider._engine)
    return repo


@pytest.fixture
def slot_repo(repo):
    repo.add(Slot(name="noon", at=STORED))
    return repo


def _names(repo, **filters):
    return [item.name for item in repo.query.filter(**filters).all().items]


@pytest.mark.parametrize(
    "lookup, value, matches",
    [
        ("lte", EARLIER, False),
        ("lte", LATER, True),
        ("lt", EARLIER, False),
        ("lt", LATER, True),
        ("gt", EARLIER, True),
        ("gt", LATER, False),
        ("gte", EARLIER, True),
        ("gte", LATER, False),
    ],
)
def test_ordering_lookups_compare_utc_instants(slot_repo, lookup, value, matches):
    expected = ["noon"] if matches else []
    assert _names(slot_repo, **{f"at__{lookup}": value}) == expected


def test_exact_and_in_match_the_same_instant_with_a_different_offset(slot_repo):
    assert _names(slot_repo, at__exact=SAME_INSTANT) == ["noon"]
    assert _names(slot_repo, at__in=[SAME_INSTANT]) == ["noon"]
    assert _names(slot_repo, at__exact=EARLIER) == []
    assert _names(slot_repo, at__in=[EARLIER, LATER]) == []


@pytest.mark.parametrize(
    "values",
    [[None, SAME_INSTANT], [SAME_INSTANT, None]],
    ids=["none_first", "none_last"],
)
def test_in_with_a_none_converts_the_other_values_to_utc(slot_repo, values):
    """SQLAlchemy types an ``in`` list from its first value, which may be None."""
    assert _names(slot_repo, at__in=values) == ["noon"]


def test_naive_filter_value_is_read_as_utc(slot_repo):
    naive_noon = datetime(2026, 10, 20, 12, 0)
    assert _names(slot_repo, at__lte=naive_noon) == ["noon"]
    assert _names(slot_repo, at__lt=naive_noon) == []


def test_an_offset_value_is_stored_as_utc_digits(test_domain, repo):
    repo.add(Slot(name="offset", at=SAME_INSTANT))

    engine = test_domain.providers["default"]._engine
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT at FROM slot")).scalar_one()

    assert stored.startswith("2026-10-20 12:00:00")


def test_an_offset_value_loads_as_the_same_utc_aware_instant(repo):
    slot = Slot(name="offset", at=SAME_INSTANT)
    repo.add(slot)

    loaded = repo.get(slot.id).at
    assert loaded == SAME_INSTANT
    assert loaded.tzinfo is UTC


def test_a_naive_value_loads_as_utc_aware(repo):
    slot = Slot(name="naive", at=datetime(2026, 10, 20, 12, 0))
    repo.add(slot)

    assert repo.get(slot.id).at == STORED
    assert repo.get(slot.id).at.tzinfo is UTC


def test_a_null_value_stays_null(repo):
    slot = Slot(name="empty")
    repo.add(slot)

    assert repo.get(slot.id).at is None
    assert _names(repo, at__isnull=True) == ["empty"]


def test_the_column_ddl_is_unchanged(test_domain, repo):
    table = repo._dao.database_model_cls.__table__
    engine = test_domain.providers["default"]._engine
    ddl = str(CreateTable(table).compile(dialect=engine.dialect))

    assert isinstance(table.c["at"].type, UTCDateTime)
    assert "\tat DATETIME" in ddl


@pytest.mark.parametrize(
    "lookup, value",
    [
        ("startswith", "2026-10-20"),
        ("endswith", "00.000000"),
        ("contains", "10-20 12:00"),
    ],
)
def test_a_string_lookup_compares_the_stored_text(slot_repo, lookup, value):
    assert _names(slot_repo, **{f"at__{lookup}": value}) == ["noon"]
