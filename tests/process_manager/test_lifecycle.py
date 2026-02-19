"""Tests for process manager lifecycle management (start, complete, end)."""

import pytest
from uuid import uuid4


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


class TestMarkAsComplete:
    def test_mark_as_complete_via_method(self, test_domain):
        """ShipmentDelivered handler calls self.mark_as_complete()."""
        order_id = str(uuid4())

        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=str(uuid4()), order_id=order_id, amount=100.0)
        )
        OrderFulfillmentPM._handle(ShipmentDelivered(order_id=order_id))

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)

        final_transition = messages[-1].to_domain_object()
        assert final_transition.is_complete is True
        assert final_transition.state["status"] == "completed"


class TestEndParameter:
    def test_end_parameter_auto_completes_pm(self, test_domain):
        """PaymentFailed handler has end=True, which auto-completes the PM."""
        order_id = str(uuid4())

        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(
            PaymentFailed(
                payment_id=str(uuid4()), order_id=order_id, reason="Insufficient funds"
            )
        )

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)

        assert len(messages) == 2
        final_transition = messages[-1].to_domain_object()
        assert final_transition.is_complete is True
        assert final_transition.state["status"] == "cancelled"


class TestCompletedPMSkipsEvents:
    def test_completed_pm_skips_subsequent_events(self, test_domain):
        """Once a PM is marked complete, subsequent events are ignored."""
        order_id = str(uuid4())

        # Complete the PM via ShipmentDelivered
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=str(uuid4()), order_id=order_id, amount=100.0)
        )
        OrderFulfillmentPM._handle(ShipmentDelivered(order_id=order_id))

        # Now send another event — should be skipped
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=str(uuid4()), order_id=order_id, amount=50.0)
        )

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)

        # Should still be only 3 transitions (the 4th was skipped)
        assert len(messages) == 3

    def test_end_parameter_completed_pm_skips_events(self, test_domain):
        """PM completed via end=True also skips subsequent events."""
        order_id = str(uuid4())

        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(
            PaymentFailed(payment_id=str(uuid4()), order_id=order_id, reason="Declined")
        )

        # PM is now complete via end=True; subsequent events should be skipped
        OrderFulfillmentPM._handle(ShipmentDelivered(order_id=order_id))

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)

        assert len(messages) == 2


class TestMultipleInstances:
    def test_multiple_pm_instances_tracked_independently(self, test_domain):
        """Different correlation values create independent PM instances."""
        order_id_1 = str(uuid4())
        order_id_2 = str(uuid4())

        # Start two independent PMs
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id_1, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id_2, customer_id="CUST-2", total=200.0)
        )

        # Advance one of them
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=str(uuid4()), order_id=order_id_1, amount=100.0)
        )

        # Verify independent state
        stream_1 = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id_1}"
        stream_2 = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id_2}"

        messages_1 = test_domain.event_store.store.read(stream_1)
        messages_2 = test_domain.event_store.store.read(stream_2)

        assert len(messages_1) == 2  # OrderPlaced + PaymentConfirmed
        assert len(messages_2) == 1  # Only OrderPlaced

        # Check state of instance 1
        transition_1 = messages_1[-1].to_domain_object()
        assert transition_1.state["status"] == "awaiting_shipment"

        # Check state of instance 2
        transition_2 = messages_2[-1].to_domain_object()
        assert transition_2.state["status"] == "awaiting_payment"
