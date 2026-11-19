"""Memory lookups compare datetimes as UTC instants, with naive read as UTC."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Date, DateTime, List

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
    at = DateTime()


class Window(BaseAggregate):
    times = List(content_type=DateTime)


class Day(BaseAggregate):
    on = Date()


@pytest.fixture
def slot_repo(test_domain):
    test_domain.register(Slot)
    test_domain.init(traverse=False)
    repo = test_domain.repository_for(Slot)
    slot = Slot(at=STORED)
    repo.add(slot)
    return repo, slot.id


def _ids(repo, **filters):
    return [item.id for item in repo.query.filter(**filters).all().items]


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
    repo, slot_id = slot_repo
    expected = [slot_id] if matches else []
    assert _ids(repo, **{f"at__{lookup}": value}) == expected


def test_exact_matches_the_same_instant_with_a_different_offset(slot_repo):
    repo, slot_id = slot_repo
    assert _ids(repo, at__exact=SAME_INSTANT) == [slot_id]
    assert _ids(repo, at__exact=EARLIER) == []


def test_in_matches_the_same_instant_with_a_different_offset(slot_repo):
    repo, slot_id = slot_repo
    assert _ids(repo, at__in=[SAME_INSTANT]) == [slot_id]
    assert _ids(repo, at__in=[EARLIER, LATER]) == []


def test_naive_filter_value_is_read_as_utc(slot_repo):
    repo, slot_id = slot_repo
    naive_noon = datetime(2026, 10, 20, 12, 0)
    assert _ids(repo, at__lte=naive_noon) == [slot_id]
    assert _ids(repo, at__lt=naive_noon) == []
    assert _ids(repo, at__exact=naive_noon) == [slot_id]


def test_naive_stored_value_is_read_as_utc(test_domain):
    test_domain.register(Slot)
    test_domain.init(traverse=False)
    repo = test_domain.repository_for(Slot)
    slot = Slot(at=datetime(2026, 10, 20, 12, 0))
    repo.add(slot)

    assert _ids(repo, at__exact=SAME_INSTANT) == [slot.id]
    assert _ids(repo, at__lte=EARLIER) == []
    assert _ids(repo, at__lte=LATER) == [slot.id]


@pytest.mark.parametrize("lookup", ["any", "overlap"])
def test_list_lookups_match_the_same_instant_with_a_different_offset(
    test_domain, lookup
):
    test_domain.register(Window)
    test_domain.init(traverse=False)
    repo = test_domain.repository_for(Window)
    window = Window(times=[STORED])
    repo.add(window)

    assert _ids(repo, **{f"times__{lookup}": [SAME_INSTANT]}) == [window.id]
    assert _ids(repo, **{f"times__{lookup}": [EARLIER]}) == []


@pytest.mark.parametrize(
    "lookup, matches",
    [("lt", False), ("lte", True), ("gt", False), ("gte", True), ("exact", True)],
)
def test_date_field_lookups_are_unchanged(test_domain, lookup, matches):
    test_domain.register(Day)
    test_domain.init(traverse=False)
    repo = test_domain.repository_for(Day)
    day = Day(on=date(2026, 10, 20))
    repo.add(day)

    expected = [day.id] if matches else []
    assert _ids(repo, **{f"on__{lookup}": date(2026, 10, 20)}) == expected


@pytest.mark.parametrize(
    "lookup, value",
    [
        ("contains", "10-20 12:00"),
        ("startswith", "2026-10-20"),
        ("endswith", "+00:00"),
    ],
)
def test_string_lookups_compare_the_string_form(slot_repo, lookup, value):
    repo, slot_id = slot_repo
    assert _ids(repo, **{f"at__{lookup}": value}) == [slot_id]
    assert _ids(repo, **{f"at__{lookup}": "1999"}) == []


def test_iso_string_filter_value_compares_as_a_string(slot_repo):
    repo, slot_id = slot_repo
    assert _ids(repo, at__exact=str(STORED)) == [slot_id]
    assert _ids(repo, at__lt="2026-10-21") == [slot_id]
    assert _ids(repo, at__lt="2026-10-19") == []
