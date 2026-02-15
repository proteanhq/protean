from datetime import datetime, timezone

from protean.fields import DateTime


def utc_now():
    return datetime.now(timezone.utc)


def test_datetime_repr_and_str():
    dt_obj1 = DateTime()
    dt_obj2 = DateTime(required=True)
    dt_obj3 = DateTime(default="2020-01-01T00:00:00")
    dt_obj4 = DateTime(default=utc_now)

    assert repr(dt_obj1) == str(dt_obj1) == "DateTime()"
    assert repr(dt_obj2) == str(dt_obj2) == "DateTime(required=True)"
    assert repr(dt_obj3) == str(dt_obj3) == "DateTime(default='2020-01-01T00:00:00')"
    assert repr(dt_obj4) == str(dt_obj4) == "DateTime(default=utc_now)"
