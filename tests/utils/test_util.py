import datetime

from protean.utils import utcnow_func


def test_utcnow_func():
    func = utcnow_func
    assert func is not None
    assert callable(func) is True

    result = func()
    assert result is not None
    assert type(result) == datetime.datetime
