from datetime import UTC, datetime, timedelta, timezone

from protean.core.value_object import BaseValueObject
from protean.fields import DateTime


def utc_now():
    return datetime.now(UTC)


class Timestamped(BaseValueObject):
    at: DateTime(required=True)


def _serialize(value):
    """Serialize a datetime through the field's ``as_dict`` (the payload path)."""
    return Timestamped(at=value).to_dict()["at"]


def test_datetime_repr_and_str():
    dt_obj1 = DateTime()
    dt_obj2 = DateTime(required=True)
    dt_obj3 = DateTime(default="2020-01-01T00:00:00")
    dt_obj4 = DateTime(default=utc_now)

    assert repr(dt_obj1) == str(dt_obj1) == "DateTime()"
    assert repr(dt_obj2) == str(dt_obj2) == "DateTime(required=True)"
    assert repr(dt_obj3) == str(dt_obj3) == "DateTime(default='2020-01-01T00:00:00')"
    assert repr(dt_obj4) == str(dt_obj4) == "DateTime(default=utc_now)"


# --- #1039: datetime payloads use isoformat(), not str() ---


def test_naive_datetime_serialized_as_isoformat():
    # ISO-8601 (T-separator) instead of the old space-separated str() form.
    # A naive datetime stays naive — its tzinfo is preserved, not forced to UTC.
    assert _serialize(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05"


def test_aware_datetime_preserves_offset():
    # An aware datetime keeps its own offset (not converted to UTC).
    aware = datetime(
        2024, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    assert _serialize(aware) == "2024-01-02T03:04:05+05:30"


def test_serialized_datetime_round_trips():
    for value in (
        datetime(2024, 1, 2, 3, 4, 5),  # naive
        datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),  # aware, UTC
        datetime(  # aware, non-UTC offset
            2024, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=5, minutes=30))
        ),
    ):
        encoded = _serialize(value)
        assert Timestamped(at=encoded).at == value
