from datetime import datetime, timezone

from protean.fields import Method


def utc_now():
    return datetime.now(timezone.utc)


def test_method_repr_and_str():
    method_obj1 = Method("fake_method")
    method_obj2 = Method("fake_method", required=True)
    method_obj4 = Method("fake_method", required=True, default=utc_now)

    assert repr(method_obj1) == str(method_obj1) == "Method()"
    assert repr(method_obj2) == str(method_obj2) == "Method(required=True)"
    assert (
        repr(method_obj4)
        == str(method_obj4)
        == "Method(required=True, default=utc_now)"
    )
