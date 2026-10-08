"""How the Message DB adapter reports a failed write, without a running database."""

from unittest.mock import MagicMock, Mock

import pytest

from protean.adapters.event_store.message_db import MessageDBStore
from protean.exceptions import ExpectedVersionError


def _store_whose_write_raises(exc: Exception) -> MessageDBStore:
    store = MessageDBStore(Mock(), {"database_uri": "postgresql://unused"})
    store._client = MagicMock()
    store._client.write.side_effect = exc
    return store


class _DatabaseError(Exception):
    def __init__(self, pgcode: str) -> None:
        super().__init__(pgcode)
        self.pgcode = pgcode


def _client_error(text: str, pgcode: str) -> ValueError:
    # The message-db client re-raises a database error as a ValueError and
    # chains the psycopg2 error, which carries the SQLSTATE in ``pgcode``.
    exc = ValueError(text)
    exc.__cause__ = _DatabaseError(pgcode)
    return exc


@pytest.mark.parametrize(
    "text",
    [
        "P0001-ERROR:  Wrong expected version: 5 (Stream: s, Stream Version: 0)",
        "P0001-FEHLER:  Wrong expected version: 5 (Stream: s, Stream Version: 0)",
    ],
    ids=["english", "localized-severity"],
)
def test_wrong_expected_version_raises_expected_version_error(text):
    store = _store_whose_write_raises(_client_error(text, "P0001"))

    with pytest.raises(ExpectedVersionError) as exc_info:
        store._write("s-1", "Event", {}, expected_version=5)

    assert str(exc_info.value) == (
        "Wrong expected version: 5 (Stream: s, Stream Version: 0)"
    )


def test_other_database_error_stays_a_value_error():
    error = _client_error("23505-ERROR:  duplicate key value", "23505")
    store = _store_whose_write_raises(error)

    with pytest.raises(ValueError) as exc_info:
        store._write("s-1", "Event", {})

    assert exc_info.value is error


def test_p0001_text_without_a_database_cause_stays_a_value_error():
    error = ValueError("P0001-ERROR:  not from the database")
    store = _store_whose_write_raises(error)

    with pytest.raises(ValueError) as exc_info:
        store._write("s-1", "Event", {})

    assert exc_info.value is error
