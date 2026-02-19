"""Tests for process manager transition event persistence and reconstitution."""

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


class TestTransitionEventGeneration:
    def test_transition_event_class_is_generated(self):
        assert OrderFulfillmentPM._transition_event_cls is not None

    def test_transition_event_class_name(self):
        assert (
            OrderFulfillmentPM._transition_event_cls.__name__
            == "_OrderFulfillmentPMTransition"
        )

    def test_transition_event_has_type_string(self):
        assert hasattr(OrderFulfillmentPM._transition_event_cls, "__type__")
        assert (
            "OrderFulfillmentPMTransition"
            in OrderFulfillmentPM._transition_event_cls.__type__
        )

    def test_transition_event_is_registered_in_events_and_commands(self, test_domain):
        type_string = OrderFulfillmentPM._transition_event_cls.__type__
        assert type_string in test_domain._events_and_commands


class TestTransitionPersistence:
    def test_transition_is_written_to_event_store(self, test_domain):
        order_id = str(uuid4())
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 1

    def test_transition_captures_state_snapshot(self, test_domain):
        order_id = str(uuid4())
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)
        transition = messages[0].to_domain_object()

        assert "state" in transition.payload
        assert "handler_name" in transition.payload
        assert "is_complete" in transition.payload

    def test_transition_records_handler_name(self, test_domain):
        order_id = str(uuid4())
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)
        transition = messages[0].to_domain_object()

        assert transition.handler_name == "on_order_placed"

    def test_multiple_transitions_maintain_version_order(self, test_domain):
        order_id = str(uuid4())

        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=str(uuid4()), order_id=order_id, amount=100.0)
        )

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 2


class TestReconstitution:
    def test_pm_is_reconstituted_from_transitions(self, test_domain):
        order_id = str(uuid4())
        payment_id = str(uuid4())

        # Create two transitions
        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(
            PaymentConfirmed(payment_id=payment_id, order_id=order_id, amount=100.0)
        )

        # Load from event store
        pm = OrderFulfillmentPM._load_or_create(order_id, is_start=False)

        assert pm is not None
        assert pm.order_id == order_id
        assert pm.payment_id == payment_id
        assert pm.status == "awaiting_shipment"
        assert pm._version == 1  # 0-indexed, so 2 transitions = version 1

    def test_reconstituted_pm_tracks_completion(self, test_domain):
        order_id = str(uuid4())

        OrderFulfillmentPM._handle(
            OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)
        )
        OrderFulfillmentPM._handle(ShipmentDelivered(order_id=order_id))

        pm = OrderFulfillmentPM._load_or_create(order_id, is_start=False)
        # Note: ShipmentDelivered calls mark_as_complete() but is NOT an end=True handler
        # The _is_complete is set inside the handler via mark_as_complete()
        # which gets captured in the transition event
        assert pm is not None
        assert pm._is_complete is True

    def test_load_or_create_returns_none_for_nonexistent(self, test_domain):
        pm = OrderFulfillmentPM._load_or_create("nonexistent-id", is_start=False)
        assert pm is None

    def test_load_or_create_with_start_creates_new(self, test_domain):
        pm = OrderFulfillmentPM._load_or_create("new-id", is_start=True)
        assert pm is not None
        assert pm._correlation_value == "new-id"
        assert pm._version == -1
        assert pm._is_complete is False
