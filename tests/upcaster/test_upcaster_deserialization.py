"""Tests for upcasting during message deserialization (Message.to_domain_object)."""

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.exceptions import DeserializationError
from protean.fields import Float, Identifier, String
from protean.utils.eventing import Message


# ── Domain elements ──────────────────────────────────────────────────────


class OrderPlaced(BaseEvent):
    __version__ = "v3"
    order_id = Identifier(required=True)
    total_amount = Float(required=True)
    currency = String(required=True)


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    total_amount = Float()
    currency = String()
    status = String(default="draft")

    @apply
    def on_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.total_amount = event.total_amount
        self.currency = event.currency
        self.status = "placed"


class UpcastV1ToV2(BaseUpcaster):
    """v1 had no currency — default to USD."""

    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


class UpcastV2ToV3(BaseUpcaster):
    """v2 had 'amount' — rename to 'total_amount'."""

    def upcast(self, data: dict) -> dict:
        data["total_amount"] = data.pop("amount")
        return data


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order, is_event_sourced=True)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.upcaster(
        UpcastV1ToV2, event_type=OrderPlaced, from_version="v1", to_version="v2"
    )
    test_domain.upcaster(
        UpcastV2ToV3, event_type=OrderPlaced, from_version="v2", to_version="v3"
    )
    test_domain.init(traverse=False)


# ── Helper to build a raw stored message dict ────────────────────────────


def _raw_message(
    type_string: str, version: str, data: dict, stream: str = "test::order-1"
) -> dict:
    """Build a raw message dict as it would appear in the event store."""
    return {
        "data": data,
        "metadata": {
            "headers": {
                "id": "msg-001",
                "type": type_string,
                "time": "2025-01-01T00:00:00+00:00",
                "stream": stream,
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": "tests.upcaster.test_upcaster_deserialization.OrderPlaced",
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": "test::order",
                "version": version,
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }


# ── Tests ────────────────────────────────────────────────────────────────


class TestV1EventUpcast:
    def test_v1_event_is_upcast_to_v3(self, test_domain):
        raw = _raw_message(
            "Test.OrderPlaced.v1",
            "v1",
            {"order_id": "order-1", "amount": 42.0},
        )
        msg = Message.deserialize(raw, validate=False)
        event = msg.to_domain_object()

        assert isinstance(event, OrderPlaced)
        assert event.order_id == "order-1"
        assert event.total_amount == 42.0
        assert event.currency == "USD"

    def test_v1_event_upcast_preserves_message_id(self, test_domain):
        raw = _raw_message(
            "Test.OrderPlaced.v1",
            "v1",
            {"order_id": "order-1", "amount": 42.0},
        )
        msg = Message.deserialize(raw, validate=False)
        event = msg.to_domain_object()

        # The original message ID is preserved through metadata
        assert event._metadata.headers.id == "msg-001"


class TestV2EventUpcast:
    def test_v2_event_is_upcast_to_v3(self, test_domain):
        raw = _raw_message(
            "Test.OrderPlaced.v2",
            "v2",
            {"order_id": "order-2", "amount": 99.99, "currency": "EUR"},
        )
        msg = Message.deserialize(raw, validate=False)
        event = msg.to_domain_object()

        assert isinstance(event, OrderPlaced)
        assert event.order_id == "order-2"
        assert event.total_amount == 99.99
        assert event.currency == "EUR"  # Preserved from v2, not overwritten


class TestCurrentVersionNoUpcast:
    def test_v3_event_passes_through_unchanged(self, test_domain):
        raw = _raw_message(
            "Test.OrderPlaced.v3",
            "v3",
            {"order_id": "order-3", "total_amount": 50.0, "currency": "GBP"},
        )
        msg = Message.deserialize(raw, validate=False)
        event = msg.to_domain_object()

        assert isinstance(event, OrderPlaced)
        assert event.order_id == "order-3"
        assert event.total_amount == 50.0
        assert event.currency == "GBP"


class TestUnknownTypeStringRaisesError:
    def test_completely_unknown_type(self, test_domain):
        raw = _raw_message(
            "Test.NonExistent.v1",
            "v1",
            {"foo": "bar"},
        )
        msg = Message.deserialize(raw, validate=False)

        with pytest.raises(DeserializationError, match="is not registered"):
            msg.to_domain_object()


class TestUpcastWorksWithEventStore:
    """Integration: write a v1-shaped event, read back, verify upcast."""

    def test_round_trip_through_event_store(self, test_domain):
        store = test_domain.event_store.store

        # Simulate a v1 event written to the store in the past
        store._write(
            "test::order-order-rt",
            "Test.OrderPlaced.v1",
            {"order_id": "order-rt", "amount": 77.77},
            {
                "headers": {
                    "id": "evt-rt-001",
                    "type": "Test.OrderPlaced.v1",
                    "time": "2025-01-01T00:00:00+00:00",
                    "stream": "test::order-order-rt",
                },
                "envelope": {"specversion": "1.0"},
                "domain": {
                    "fqn": "tests.upcaster.test_upcaster_deserialization.OrderPlaced",
                    "kind": "EVENT",
                    "origin_stream": None,
                    "stream_category": "test::order",
                    "version": "v1",
                    "sequence_id": "0",
                    "asynchronous": True,
                },
            },
        )

        # Read it back — should be upcast to v3
        messages = store.read("test::order-order-rt")
        assert len(messages) == 1

        event = messages[0].to_domain_object()
        assert isinstance(event, OrderPlaced)
        assert event.order_id == "order-rt"
        assert event.total_amount == 77.77
        assert event.currency == "USD"
