"""Run the example on ``docs/concepts/internals/event-upcasting.md``.

``001.py`` defines ``OrderPlaced`` at version 3. ``AddCurrency`` (v1 to v2,
registered with the decorator) adds ``currency="USD"``. ``RenameAmount`` (v2
to v3, registered directly) renames ``amount`` to ``total_amount``. The tests
write raw old-version events into the memory event store, the way an old
deployment would have left them, and read them back.
"""

import pytest

from protean.exceptions import ConfigurationError, DeserializationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

STREAM = "ordering::order-ord-1"


@pytest.fixture
def example():
    module = load_example("concepts/internals/event-upcasting/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def write_raw(example, type_string, version, data, position=0):
    example.domain.event_store.store._write(
        STREAM,
        type_string,
        data,
        {
            "headers": {
                "id": f"evt-{position}",
                "type": type_string,
                "time": "2025-01-01T00:00:00+00:00",
                "stream": STREAM,
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": "OrderPlaced",
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": "ordering::order",
                "version": version,
                "sequence_id": str(position),
                "asynchronous": True,
            },
        },
        position - 1,
    )


def read_one(example):
    [message] = example.domain.event_store.store.read(STREAM)
    return message


def test_v1_payload_runs_through_both_upcasters(example):
    write_raw(
        example, "Ordering.OrderPlaced.v1", 1, {"order_id": "ord-1", "amount": 42.0}
    )

    event = read_one(example).to_domain_object()

    assert isinstance(event, example.OrderPlaced)
    assert event.payload == {
        "order_id": "ord-1",
        "total_amount": 42.0,
        "currency": "USD",
    }


def test_v2_payload_runs_only_the_last_upcaster(example):
    data = {"order_id": "ord-1", "amount": 9.5, "currency": "EUR"}
    write_raw(example, "Ordering.OrderPlaced.v2", 2, data)

    event = read_one(example).to_domain_object()

    assert event.total_amount == 9.5
    assert event.currency == "EUR"


def test_current_version_payload_is_not_upcast(example):
    data = {"order_id": "ord-1", "total_amount": 5.0, "currency": "GBP"}
    write_raw(example, "Ordering.OrderPlaced.v3", 3, data)

    event = read_one(example).to_domain_object()

    assert event.payload == data


def test_upcast_event_keeps_the_stored_type_string(example):
    write_raw(
        example, "Ordering.OrderPlaced.v1", 1, {"order_id": "ord-1", "amount": 1.0}
    )

    message = read_one(example)
    event = message.to_domain_object()

    assert event._metadata.headers.type == "Ordering.OrderPlaced.v1"
    # Pins the current behaviour the page describes: BaseEvent.__init__ resets
    # the domain version to the class's version. If the event starts keeping
    # the stored version, update this assertion and the page together.
    assert event._metadata.domain.version == 3
    assert message.metadata.domain.version == 1


def test_aggregate_loads_from_a_v1_creation_event(example):
    write_raw(
        example, "Ordering.OrderPlaced.v1", 1, {"order_id": "ord-1", "amount": 42.0}
    )

    order = example.domain.repository_for(example.Order).get("ord-1")

    assert order.total_amount == 42.0
    assert order.currency == "USD"


def test_version_with_no_chain_fails_to_deserialize(example):
    write_raw(example, "Ordering.OrderPlaced.v9", 9, {"order_id": "ord-1"})

    with pytest.raises(DeserializationError, match="is not registered"):
        read_one(example).to_domain_object()


def test_chain_maps_each_old_type_string_to_the_current_class(example):
    chain = example.domain._upcaster_chain

    assert chain.resolve_event_class("Ordering.OrderPlaced.v1") is example.OrderPlaced
    assert chain.resolve_event_class("Ordering.OrderPlaced.v2") is example.OrderPlaced
    assert chain.resolve_event_class("Ordering.OrderPlaced.v3") is None


def test_chain_that_misses_the_current_version_fails_at_init():
    module = load_example("concepts/internals/event-upcasting/001.py")
    module.OrderPlaced.__version__ = 4
    with pytest.raises(ConfigurationError, match="no event is registered"):
        module.domain.init(traverse=False)
