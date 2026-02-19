"""Tests for event dispatch and correlation in process managers."""

import pytest
from uuid import uuid4

from protean.core.process_manager import _resolve_correlation_value
from protean.exceptions import ConfigurationError

from .elements import (
    Order,
    OrderFulfillmentPM,
    OrderPlaced,
    Payment,
    PaymentConfirmed,
    PaymentFailed,
    Shipping,
    ShipmentDelivered,
)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.register(Payment)
    test_domain.register(PaymentConfirmed, part_of=Payment)
    test_domain.register(PaymentFailed, part_of=Payment)
    test_domain.register(Shipping)
    test_domain.register(ShipmentDelivered, part_of=Shipping)
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)


class TestResolveCorrelationValue:
    def test_string_correlate(self):
        event = OrderPlaced(order_id="ORD-123", customer_id="CUST-1", total=100.0)
        result = _resolve_correlation_value(event, "order_id")
        assert result == "ORD-123"

    def test_dict_correlate(self):
        event = OrderPlaced(order_id="ORD-456", customer_id="CUST-2", total=200.0)
        result = _resolve_correlation_value(event, {"my_field": "order_id"})
        assert result == "ORD-456"

    def test_invalid_correlate_spec(self):
        event = OrderPlaced(order_id="ORD-789", customer_id="CUST-3", total=300.0)
        with pytest.raises(ConfigurationError):
            _resolve_correlation_value(event, 12345)


class TestStartEvent:
    def test_start_event_creates_new_pm_instance(self, test_domain):
        order_id = str(uuid4())
        event = OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)

        OrderFulfillmentPM._handle(event)

        # Verify the PM was persisted by reading the transition from the event store
        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 1

    def test_start_event_sets_pm_fields(self, test_domain):
        order_id = str(uuid4())
        event = OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)

        OrderFulfillmentPM._handle(event)

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)

        transition = messages[0].to_domain_object()
        assert transition.state["order_id"] == order_id
        assert transition.state["status"] == "awaiting_payment"


class TestSubsequentEvents:
    def test_subsequent_event_loads_existing_pm(self, test_domain):
        order_id = str(uuid4())

        # Start the PM
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )

        # Process a subsequent event
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=str(uuid4()), order_id=order_id, amount=100.0)
        )

        # Should have 2 transitions now
        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 2

    def test_subsequent_event_updates_pm_state(self, test_domain):
        order_id = str(uuid4())

        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=str(uuid4()), order_id=order_id, amount=100.0)
        )

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)

        latest_transition = messages[-1].to_domain_object()
        assert latest_transition.state["status"] == "awaiting_shipment"
        assert latest_transition.state["payment_id"] is not None


class TestNonStartEventWithNoPM:
    def test_non_start_event_with_no_existing_pm_is_skipped(self, test_domain):
        """A non-start event for a correlation value with no existing PM should be skipped."""
        order_id = str(uuid4())

        # This is not a start event, and no PM exists for this order_id
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=str(uuid4()), order_id=order_id, amount=100.0)
        )

        # No transition should be persisted
        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 0


class TestFullLifecycle:
    def test_full_order_fulfillment_lifecycle(self, test_domain):
        order_id = str(uuid4())
        payment_id = str(uuid4())

        # Step 1: Place order (start)
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )

        # Step 2: Confirm payment
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=payment_id, order_id=order_id, amount=100.0)
        )

        # Step 3: Ship delivered (mark_as_complete)
        OrderFulfillmentPM._handle(ShipmentDelivered(order_id=order_id))

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)

        assert len(messages) == 3

        # Check final state
        final = messages[-1].to_domain_object()
        assert final.state["status"] == "completed"
        assert final.is_complete is True
