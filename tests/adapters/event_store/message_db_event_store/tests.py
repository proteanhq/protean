import json
import pytest

from psycopg2 import extensions

from protean import Domain
from protean.adapters.event_store.message_db import MessageDBStore
from protean.exceptions import ConfigurationError


def test_retrieving_message_store_from_domain(test_domain):
    assert test_domain.event_store is not None
    assert test_domain.event_store.store is not None
    assert isinstance(test_domain.event_store.store, MessageDBStore)


def test_error_on_message_db_initialization():
    domain = Domain()
    domain.config["EVENT_STORE"][
        "DATABASE_URI"
    ] = "postgresql://message_store@localhost:5433/dummy"

    with pytest.raises(ConfigurationError) as exc:
        domain.event_store.store._write("testStream-123", "Event1", {"foo": f"bar"})

    assert 'FATAL:  database "dummy" does not exist' in str(exc.value)

    # Reset config value. # FIXME Config should be an argument to the domain
    domain.config["EVENT_STORE"][
        "DATABASE_URI"
    ] = "postgresql://message_store@localhost:5433/message_store"


def test_write_to_event_store(test_domain):
    position = test_domain.event_store.store._write(
        "testStream-123", "Event1", {"foo": "bar"}
    )

    assert position == 0


def test_multiple_writes_to_event_store(test_domain):
    for i in range(5):
        position = test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": f"bar{i}"}
        )

    position = test_domain.event_store.store._write(
        "testStream-123", "Event1", {"foo": "bar"}
    )
    assert position == 5


def test_reading_stream_message(test_domain):
    test_domain.event_store.store._write("testStream-123", "Event1", {"foo": "bar"})

    messages = test_domain.event_store.store._read("testStream-123")

    assert len(messages) == 1
    assert messages[0]["position"] == 0
    assert messages[0]["data"] == json.dumps({"foo": "bar"})


def test_reading_multiple_stream_messages(test_domain):
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": f"bar{i}"}
        )

    messages = test_domain.event_store.store._read("testStream-123")

    assert len(messages) == 5
    assert messages[4]["data"] == json.dumps({"foo": "bar4"})


def test_reading_category_message(test_domain):
    test_domain.event_store.store._write("testStream-123", "Event1", {"foo": "bar"})

    messages = test_domain.event_store.store._read("testStream")

    assert len(messages) == 1
    assert messages[0]["position"] == 0
    assert messages[0]["data"] == json.dumps({"foo": "bar"})


def test_reading_multiple_category_messages(test_domain):
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": f"bar{i}"}
        )

    messages = test_domain.event_store.store._read("testStream")

    assert len(messages) == 5
    assert messages[4]["data"] == json.dumps({"foo": "bar4"})


def test_reading_targeted_stream_messages(test_domain):
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": f"bar{i}"}
        )
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-456", "Event1", {"foo": f"baz{i}"}
        )

    messages = test_domain.event_store.store._read("testStream-456")

    assert len(messages) == 5
    assert messages[4]["data"] == json.dumps({"foo": "baz4"})


def test_read_last_message(test_domain):
    for i in range(5):
        test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": f"bar{i}"}
        )

    message = test_domain.event_store.store._read_last_message("testStream-123")
    assert message["position"] == 4
