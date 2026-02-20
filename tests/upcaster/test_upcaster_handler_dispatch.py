"""Tests for upcasting during event handler and projector dispatch.

These tests verify that old-version events are upcast before reaching
@handle / @on methods when dispatched via HandlerMixin._handle(Message).
This covers the projection rebuild scenario: a projector replaying all
events from the store receives upcast events transparently.
"""

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String
from protean.utils.eventing import Message
from protean.utils.mixins import handle


# ── Domain elements ──────────────────────────────────────────────────────


class OrderPlaced(BaseEvent):
    """Current version — v2 renamed 'amount' to 'total' and added currency."""

    __version__ = "v2"
    order_id = Identifier(required=True)
    total = Float(required=True)
    currency = String(required=True)


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    total = Float(default=0.0)
    currency = String(default="USD")

    @apply
    def on_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.total = event.total
        self.currency = event.currency


class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    """v1 had 'amount' instead of 'total' and no currency field."""

    def upcast(self, data: dict) -> dict:
        data["total"] = data.pop("amount")
        data["currency"] = "USD"
        return data


# ── Tracking containers for handler assertions ───────────────────────────

_handler_received_events: list[OrderPlaced] = []
_projector_received_events: list[OrderPlaced] = []


class OrderAnalyticsHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        _handler_received_events.append(event)


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    total = Float()
    currency = String()


class OrderSummaryProjector(BaseProjector):
    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        _projector_received_events.append(event)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order, is_event_sourced=True)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(OrderAnalyticsHandler, part_of=Order)
    test_domain.register(OrderSummary)
    test_domain.register(
        OrderSummaryProjector, projector_for=OrderSummary, aggregates=[Order]
    )
    test_domain.upcaster(
        UpcastOrderPlacedV1ToV2,
        event_type=OrderPlaced,
        from_version="v1",
        to_version="v2",
    )
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def clear_tracking():
    """Clear tracking lists before each test."""
    _handler_received_events.clear()
    _projector_received_events.clear()


def _v1_message(order_id: str = "order-1", amount: float = 42.0) -> Message:
    """Build a Message object representing a v1 OrderPlaced event."""
    raw = {
        "data": {"order_id": order_id, "amount": amount},
        "metadata": {
            "headers": {
                "id": f"evt-{order_id}",
                "type": "Test.OrderPlaced.v1",
                "time": "2025-01-01T00:00:00+00:00",
                "stream": f"test::order-{order_id}",
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": "tests.upcaster.test_upcaster_handler_dispatch.OrderPlaced",
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": "test::order",
                "version": "v1",
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }
    return Message.deserialize(raw, validate=False)


def _v2_message(
    order_id: str = "order-2", total: float = 99.0, currency: str = "EUR"
) -> Message:
    """Build a Message object representing a v2 (current) OrderPlaced event."""
    raw = {
        "data": {"order_id": order_id, "total": total, "currency": currency},
        "metadata": {
            "headers": {
                "id": f"evt-{order_id}",
                "type": "Test.OrderPlaced.v2",
                "time": "2025-01-01T00:00:00+00:00",
                "stream": f"test::order-{order_id}",
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": "tests.upcaster.test_upcaster_handler_dispatch.OrderPlaced",
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": "test::order",
                "version": "v2",
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }
    return Message.deserialize(raw, validate=False)


# ── Tests: Event Handler ─────────────────────────────────────────────────


class TestEventHandlerReceivesUpcastEvent:
    """Event handler's @handle method receives upcast event via _handle(Message)."""

    def test_handler_receives_upcast_v1_event(self, test_domain):
        msg = _v1_message(order_id="order-eh-1", amount=42.0)

        OrderAnalyticsHandler._handle(msg)

        assert len(_handler_received_events) == 1
        event = _handler_received_events[0]
        assert isinstance(event, OrderPlaced)
        assert event.order_id == "order-eh-1"
        assert event.total == 42.0  # renamed from 'amount'
        assert event.currency == "USD"  # added by upcaster

    def test_handler_receives_current_version_unchanged(self, test_domain):
        msg = _v2_message(order_id="order-eh-2", total=99.0, currency="EUR")

        OrderAnalyticsHandler._handle(msg)

        assert len(_handler_received_events) == 1
        event = _handler_received_events[0]
        assert event.total == 99.0
        assert event.currency == "EUR"


# ── Tests: Projector ─────────────────────────────────────────────────────


class TestProjectorReceivesUpcastEvent:
    """Projector's @on method receives upcast event via _handle(Message).

    This simulates the projection rebuild scenario: a projector replaying
    all events from the store encounters both old and new version events.
    """

    def test_projector_receives_upcast_v1_event(self, test_domain):
        msg = _v1_message(order_id="order-proj-1", amount=77.0)

        OrderSummaryProjector._handle(msg)

        assert len(_projector_received_events) == 1
        event = _projector_received_events[0]
        assert isinstance(event, OrderPlaced)
        assert event.order_id == "order-proj-1"
        assert event.total == 77.0  # renamed from 'amount'
        assert event.currency == "USD"  # added by upcaster

    def test_projector_receives_current_version_unchanged(self, test_domain):
        msg = _v2_message(order_id="order-proj-2", total=150.0, currency="GBP")

        OrderSummaryProjector._handle(msg)

        assert len(_projector_received_events) == 1
        event = _projector_received_events[0]
        assert event.total == 150.0
        assert event.currency == "GBP"

    def test_projector_handles_mixed_version_stream(self, test_domain):
        """Simulate replaying a stream with both v1 and v2 events."""
        messages = [
            _v1_message(order_id="order-mix-1", amount=10.0),
            _v1_message(order_id="order-mix-2", amount=20.0),
            _v2_message(order_id="order-mix-3", total=30.0, currency="EUR"),
            _v1_message(order_id="order-mix-4", amount=40.0),
            _v2_message(order_id="order-mix-5", total=50.0, currency="GBP"),
        ]

        for msg in messages:
            OrderSummaryProjector._handle(msg)

        assert len(_projector_received_events) == 5

        # All events are OrderPlaced v2 instances
        for event in _projector_received_events:
            assert isinstance(event, OrderPlaced)
            assert hasattr(event, "total")
            assert hasattr(event, "currency")

        # v1 events got USD default
        assert _projector_received_events[0].currency == "USD"
        assert _projector_received_events[0].total == 10.0
        assert _projector_received_events[1].currency == "USD"
        assert _projector_received_events[3].currency == "USD"

        # v2 events kept their original currency
        assert _projector_received_events[2].currency == "EUR"
        assert _projector_received_events[4].currency == "GBP"
