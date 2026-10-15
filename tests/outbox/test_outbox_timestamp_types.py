"""The outbox and consume-idempotency timestamps stay ``datetime`` columns.

These fields carry a validator that gives parsed values a stdlib ``timezone``.
The SQL adapter reads each field's Python type to pick its column type, so the
validator must not hide ``datetime`` from it, or the column becomes a string.
"""

import datetime

import pytest

from protean.adapters.repository.sqlalchemy import _resolve_python_type
from protean.utils.consume_idempotency import ProcessedMessage
from protean.utils.outbox import Outbox
from protean.utils.reflection import fields


@pytest.mark.parametrize(
    ("model", "name"),
    [
        (Outbox, "created_at"),
        (Outbox, "published_at"),
        (Outbox, "last_processed_at"),
        (Outbox, "next_retry_at"),
        (Outbox, "locked_until"),
        (ProcessedMessage, "processed_at"),
    ],
)
def test_timestamp_resolves_to_datetime_for_the_sql_adapter(model, name):
    assert _resolve_python_type(fields(model)[name]) is datetime.datetime
