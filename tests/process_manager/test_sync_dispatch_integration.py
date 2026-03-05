"""Integration tests: aggregate → UoW → sync dispatch → Process Manager.

These tests verify that the full sync dispatch path works end-to-end:
aggregate raises event → UoW commit → handlers_for() → PM._handle() →
PM transition persisted in event store.

Also tests the async dispatch path (Message-based) that the Engine uses:
event → Message → PM._handle(message) → to_domain_object() → handler.

All existing PM tests call _handle() directly with raw events. These tests
exercise the complete path through UoW sync and Message-based async dispatch.
"""

import pytest
from uuid import uuid4

from protean.core.unit_of_work import UnitOfWork
from protean.utils.eventing import Message
from protean.utils.globals import current_domain

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


class TestSyncDispatchStartEvent:
    """Saving an aggregate that raises a PM start event should trigger the PM."""

    def test_aggregate_save_triggers_pm_via_uow(self, test_domain):
        """Full path: Order.place() → repo.add() → UoW commit → sync dispatch → PM._handle()"""
        order = Order.place(customer_id="CUST-1", total=100.0)

        with UnitOfWork():
            repo = current_domain.repository_for(Order)
            repo.add(order)

        # Verify PM transition was persisted
        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order.id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 1

        transition = messages[0].to_domain_object()
        assert transition.state["order_id"] == str(order.id)
        assert transition.state["status"] == "awaiting_payment"

    def test_handlers_for_returns_pm_for_start_event(self, test_domain):
        """Verify handlers_for() includes the PM for a start event."""
        event = OrderPlaced(order_id=str(uuid4()), customer_id="CUST-1", total=100.0)
        handlers = current_domain.handlers_for(event)
        assert OrderFulfillmentPM in handlers


class TestSyncDispatchMultiStep:
    """Full lifecycle through sync dispatch across multiple aggregates."""

    def test_two_step_lifecycle_via_sync_dispatch(self, test_domain):
        """Place order (PM starts) → confirm payment (PM advances)."""
        # Step 1: Place order
        order = Order.place(customer_id="CUST-1", total=100.0)
        with UnitOfWork():
            current_domain.repository_for(Order).add(order)

        # Step 2: Confirm payment (from a different aggregate)
        payment = Payment.confirm(order_id=str(order.id), amount=100.0)
        with UnitOfWork():
            current_domain.repository_for(Payment).add(payment)

        # Verify PM has 2 transitions
        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order.id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 2

        transition = messages[-1].to_domain_object()
        assert transition.state["status"] == "awaiting_shipment"
        assert transition.state["payment_id"] == str(payment.id)

    def test_full_lifecycle_via_sync_dispatch(self, test_domain):
        """Place → pay → ship: PM completes through sync dispatch."""
        # Step 1: Place order
        order = Order.place(customer_id="CUST-1", total=100.0)
        with UnitOfWork():
            current_domain.repository_for(Order).add(order)

        # Step 2: Confirm payment
        payment = Payment.confirm(order_id=str(order.id), amount=100.0)
        with UnitOfWork():
            current_domain.repository_for(Payment).add(payment)

        # Step 3: Ship delivered
        shipping = Shipping.deliver(order_id=str(order.id))
        with UnitOfWork():
            current_domain.repository_for(Shipping).add(shipping)

        # Verify full lifecycle
        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order.id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 3

        final = messages[-1].to_domain_object()
        assert final.state["status"] == "completed"
        assert final.is_complete is True

    def test_failure_path_via_sync_dispatch(self, test_domain):
        """Place → payment failed: PM ends via sync dispatch."""
        order = Order.place(customer_id="CUST-1", total=50.0)
        with UnitOfWork():
            current_domain.repository_for(Order).add(order)

        payment = Payment.fail(order_id=str(order.id), reason="insufficient_funds")
        with UnitOfWork():
            current_domain.repository_for(Payment).add(payment)

        stream_name = f"{OrderFulfillmentPM.meta_.stream_category}-{order.id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 2

        final = messages[-1].to_domain_object()
        assert final.state["status"] == "cancelled"
        assert final.is_complete is True


class TestMessageBasedDispatch:
    """Simulate the async/Engine path: event → Message → PM._handle(message).

    In the Engine's async path, events arrive as Message objects (deserialized
    from Redis). The PM's _handle() calls to_domain_object() to reconstruct
    the event before dispatching to handlers.

    These tests verify this Message-based path works correctly.
    """

    def test_event_store_message_type_matches_handler_key(self, test_domain):
        """The type string in event store Messages must match PM._handlers keys."""
        order = Order.place(customer_id="CUST-1", total=100.0)

        with UnitOfWork():
            current_domain.repository_for(Order).add(order)

        # Read event from event store — returns Message objects
        aggregate_stream = f"test::order-{order.id}"
        event_messages = test_domain.event_store.store.read(aggregate_stream)
        assert len(event_messages) >= 1

        # The type string should use the domain's camel_case_name, not the aggregate name
        expected_type = OrderPlaced.__type__  # e.g., "Test.OrderPlaced.v1"
        order_placed_msg = None
        for msg in event_messages:
            if msg.metadata.headers.type == expected_type:
                order_placed_msg = msg
                break
        assert order_placed_msg is not None, (
            f"OrderPlaced message with type '{expected_type}' not found. "
            f"Available types: {[m.metadata.headers.type for m in event_messages]}"
        )

        # Verify the PM handler key matches
        assert expected_type in OrderFulfillmentPM._handlers

    def test_message_round_trip_preserves_type(self, test_domain):
        """Event → Message → dict → Message → to_domain_object() should preserve type."""
        order = Order.place(customer_id="CUST-1", total=100.0)

        with UnitOfWork():
            current_domain.repository_for(Order).add(order)

        aggregate_stream = f"test::order-{order.id}"
        messages = test_domain.event_store.store.read(aggregate_stream)

        expected_type = OrderPlaced.__type__
        order_placed_msg = None
        for msg in messages:
            if msg.metadata.headers.type == expected_type:
                order_placed_msg = msg
                break
        assert order_placed_msg is not None

        # Simulate Redis round-trip: Message → dict → Message
        msg_dict = order_placed_msg.to_dict()
        reconstructed = Message.deserialize(msg_dict)

        # Verify type is preserved through round-trip
        assert reconstructed.metadata.headers.type == expected_type

        # Verify to_domain_object() works
        domain_obj = reconstructed.to_domain_object()
        assert domain_obj.__class__.__name__ == "OrderPlaced"
        assert domain_obj.__class__.__type__ == expected_type

        # Verify the handler lookup would work
        handlers = OrderFulfillmentPM._handlers.get(domain_obj.__class__.__type__)
        assert handlers is not None and len(handlers) > 0

    def test_pm_handle_with_message_from_event_store(self, test_domain):
        """Read event from event store as Message, call PM._handle — async path."""
        # Use a unique order_id that won't collide with sync dispatch
        order_id = str(uuid4())
        event = OrderPlaced(order_id=order_id, customer_id="CUST-1", total=100.0)

        # Build proper metadata using the actual type string
        from protean.utils.eventing import (
            DomainMeta,
            MessageEnvelope,
            MessageHeaders,
            Metadata,
        )

        headers = MessageHeaders(
            id=f"test::order-{order_id}-0",
            type=OrderPlaced.__type__,
            stream=f"test::order-{order_id}",
        )
        envelope = MessageEnvelope.build(event.payload)
        domain_meta = DomainMeta(
            fqn="tests.process_manager.elements.OrderPlaced",
            kind="EVENT",
            stream_category="test::order",
            version="v1",
        )
        metadata = Metadata(headers=headers, envelope=envelope, domain=domain_meta)

        # Create Message (as the StreamSubscription would receive from Redis)
        message = Message(data=event.payload, metadata=metadata)

        # Call PM._handle with the Message (async path)
        OrderFulfillmentPM._handle(message)

        # Verify PM transition was persisted
        pm_stream = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        transitions = test_domain.event_store.store.read(pm_stream)
        assert len(transitions) == 1

        transition = transitions[0].to_domain_object()
        assert transition.state["order_id"] == order_id
        assert transition.state["status"] == "awaiting_payment"

    def test_pm_multi_step_with_messages(self, test_domain):
        """Multi-step PM lifecycle using Message objects (full async simulation)."""
        from protean.utils.eventing import (
            DomainMeta,
            MessageEnvelope,
            MessageHeaders,
            Metadata,
        )

        order_id = str(uuid4())
        payment_id = str(uuid4())

        def make_message(event_cls, event_data, stream_category, stream_id):
            event = event_cls(**event_data)
            headers = MessageHeaders(
                id=f"{stream_category}-{stream_id}-0",
                type=event_cls.__type__,
                stream=f"{stream_category}-{stream_id}",
            )
            envelope = MessageEnvelope.build(event.payload)
            domain_meta = DomainMeta(
                fqn=f"tests.process_manager.elements.{event_cls.__name__}",
                kind="EVENT",
                stream_category=stream_category,
                version="v1",
            )
            metadata = Metadata(headers=headers, envelope=envelope, domain=domain_meta)
            return Message(data=event.payload, metadata=metadata)

        # Step 1: Order placed (start) — via Message
        msg1 = make_message(
            OrderPlaced,
            {"order_id": order_id, "customer_id": "CUST-1", "total": 100.0},
            "test::order",
            order_id,
        )
        OrderFulfillmentPM._handle(msg1)

        # Step 2: Payment confirmed — via Message
        msg2 = make_message(
            PaymentConfirmed,
            {"payment_id": payment_id, "order_id": order_id, "amount": 100.0},
            "test::payment",
            payment_id,
        )
        OrderFulfillmentPM._handle(msg2)

        # Verify PM has 2 transitions
        pm_stream = f"{OrderFulfillmentPM.meta_.stream_category}-{order_id}"
        transitions = test_domain.event_store.store.read(pm_stream)
        assert len(transitions) == 2

        final = transitions[-1].to_domain_object()
        assert final.state["status"] == "awaiting_shipment"
        assert final.state["payment_id"] == payment_id
