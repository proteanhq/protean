"""Datetime lookups compare UTC instants on every provider, with naive read as UTC.

Each case stores one ``Slot`` at 12:00 UTC and filters it with a value that
carries a different UTC offset, or no offset at all.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, String
from protean.utils import ensure_utc_aware

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


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Slot)


@pytest.fixture
def slot_repo(test_domain, db):
    # Requests ``db`` so the table exists before the row is added.
    repo = test_domain.repository_for(Slot)
    repo.add(Slot(name="noon", at=STORED))
    return repo


def _names(repo, **filters):
    return [item.name for item in repo.query.filter(**filters).all().items]


@pytest.mark.basic_storage
class TestDatetimeOffsetLookups:
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
    def test_ordering_lookups_compare_utc_instants(
        self, slot_repo, lookup, value, matches
    ):
        expected = ["noon"] if matches else []
        assert _names(slot_repo, **{f"at__{lookup}": value}) == expected

    def test_exact_matches_the_same_instant_with_a_different_offset(self, slot_repo):
        assert _names(slot_repo, at__exact=SAME_INSTANT) == ["noon"]
        assert _names(slot_repo, at__exact=EARLIER) == []

    def test_in_matches_the_same_instant_with_a_different_offset(self, slot_repo):
        assert _names(slot_repo, at__in=[SAME_INSTANT]) == ["noon"]
        assert _names(slot_repo, at__in=[EARLIER, LATER]) == []

    def test_naive_filter_value_is_read_as_utc(self, slot_repo):
        naive_noon = datetime(2026, 10, 20, 12, 0)
        assert _names(slot_repo, at__lte=naive_noon) == ["noon"]
        assert _names(slot_repo, at__lt=naive_noon) == []

    def test_saved_offset_value_loads_as_the_same_instant(self, test_domain):
        repo = test_domain.repository_for(Slot)
        slot = Slot(name="offset", at=SAME_INSTANT)
        repo.add(slot)

        # PostgreSQL loads a naive UTC value, so the check compares instants.
        assert ensure_utc_aware(repo.get(slot.id).at) == SAME_INSTANT
