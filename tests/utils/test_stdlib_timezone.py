"""Datetimes parsed by the framework's own models carry a stdlib ``timezone``.

pydantic-core gives a parsed offset its own ``TzInfo`` class. Freeing one while
Python 3.11 tears its modules down can crash the interpreter, so the framework
swaps it for an equal ``datetime.timezone`` wherever it parses a datetime.
"""

from datetime import UTC, datetime, timedelta, timezone

from pydantic import TypeAdapter

from protean.utils import StdlibDatetime, _stdlib_timezone
from protean.utils.eventing import MessageHeaders


def test_a_pydantic_tzinfo_is_replaced_with_an_equal_stdlib_timezone():
    parsed = TypeAdapter(datetime).validate_python("2024-01-02T03:04:05+05:30")
    assert type(parsed.tzinfo) is not timezone

    replaced = _stdlib_timezone(parsed)

    assert type(replaced.tzinfo) is timezone
    assert replaced == parsed
    assert replaced.utcoffset() == timedelta(hours=5, minutes=30)


def test_naive_aware_and_non_datetime_values_pass_through_unchanged():
    naive = datetime(2024, 1, 2, 3, 4, 5)
    aware = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)

    assert _stdlib_timezone(naive) is naive
    assert _stdlib_timezone(aware) is aware
    assert _stdlib_timezone(None) is None


def test_the_shared_type_parses_to_a_stdlib_timezone():
    parsed = TypeAdapter(StdlibDatetime).validate_python("2024-01-02T03:04:05Z")

    assert type(parsed.tzinfo) is timezone
    assert parsed == datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_message_headers_read_from_strings_carry_a_stdlib_timezone():
    headers = MessageHeaders(
        id="msg-1",
        type="Test.Event.v1",
        time="2024-01-02T03:04:05Z",
        deadline="2024-01-02T04:04:05+05:30",
    )

    assert type(headers.time.tzinfo) is timezone
    assert type(headers.deadline.tzinfo) is timezone
    assert headers.deadline.utcoffset() == timedelta(hours=5, minutes=30)
