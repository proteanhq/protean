"""Tests: Process Manager handling of external events from other domains.

ShopStream's OrderCheckoutSaga uses external events (StockReserved from
Inventory, PaymentSucceeded from Payments). These events are registered
via register_external_event() rather than being domain-owned events.

This test verifies that PMs correctly:
1. Wire handlers keyed by external event __type__ strings
2. Find PM handlers via handlers_for() for external events
3. Dispatch via sync path (UoW) for external events
4. Dispatch via Message path (Engine) for external events

The key difference from test_sync_dispatch_integration.py: those tests use
events that are ALL registered with the same test domain. These tests use
events from a simulated "foreign" domain.
"""

import pytest
from uuid import uuid4

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.process_manager import BaseProcessManager
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Float, Identifier, String
from protean.utils.eventing import Message
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# --- Internal aggregate + event (part of test domain) ---


class Order(BaseAggregate):
    customer_id: Identifier()
    total: Float()

    @classmethod
    def place(cls, customer_id: str, total: float):
        order = cls(customer_id=customer_id, total=total)
        order.raise_(
            OrderPlaced(order_id=str(order.id), customer_id=customer_id, total=total)
        )
        return order


class OrderPlaced(BaseEvent):
    order_id: Identifier()
    customer_id: Identifier()
    total: Float()


# --- External events (NOT registered with test domain, simulating foreign domain) ---


class StockReserved(BaseEvent):
    """Simulates an event from the Inventory domain."""

    __version__ = "v1"
    inventory_item_id: Identifier()
    reservation_id: Identifier()
    order_id: Identifier()
    quantity: Float()


class PaymentSucceeded(BaseEvent):
    """Simulates an event from the Payments domain."""

    __version__ = "v1"
    payment_id: Identifier()
    order_id: Identifier()
    amount: Float()


# --- PM that mixes internal + external events ---


class CrossDomainPM(BaseProcessManager):
    order_id: Identifier()
    reservation_id: Identifier()
    payment_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_reservation"

    @handle(StockReserved, correlate="order_id")
    def on_stock_reserved(self, event: StockReserved) -> None:
        self.reservation_id = event.reservation_id
        self.status = "awaiting_payment"

    @handle(PaymentSucceeded, correlate="order_id")
    def on_payment_succeeded(self, event: PaymentSucceeded) -> None:
        self.payment_id = event.payment_id
        self.status = "completed"
        self.mark_as_complete()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    # Register internal elements
    test_domain.register(Order)
    test_domain.register(OrderPlaced, part_of=Order)

    # Register PM with stream categories that include foreign streams
    test_domain.register(
        CrossDomainPM,
        stream_categories=[
            "test::order",
            "inventory::inventory_item",
            "payments::payment",
        ],
    )

    # Register external events (simulating what ShopStream does)
    test_domain.register_external_event(StockReserved, "Inventory.StockReserved.v1")
    test_domain.register_external_event(
        PaymentSucceeded, "Payments.PaymentSucceeded.v1"
    )

    test_domain.init(traverse=False)


class TestExternalEventHandlerWiring:
    """Verify PM handlers are correctly keyed by external event type strings."""

    def test_internal_event_type_in_handlers(self, test_domain):
        """Internal event should be keyed by domain-assigned type string."""
        assert OrderPlaced.__type__ in CrossDomainPM._handlers
        assert OrderPlaced.__type__ == f"{test_domain.camel_case_name}.OrderPlaced.v1"

    def test_external_event_type_in_handlers(self, test_domain):
        """External events should be keyed by their registered type strings."""
        assert "Inventory.StockReserved.v1" in CrossDomainPM._handlers
        assert "Payments.PaymentSucceeded.v1" in CrossDomainPM._handlers

    def test_external_event_type_attribute(self, test_domain):
        """register_external_event should set __type__ on the event class."""
        assert StockReserved.__type__ == "Inventory.StockReserved.v1"
        assert PaymentSucceeded.__type__ == "Payments.PaymentSucceeded.v1"

    def test_external_events_in_events_and_commands(self, test_domain):
        """External events should be in _events_and_commands for deserialization."""
        assert "Inventory.StockReserved.v1" in test_domain._events_and_commands
        assert "Payments.PaymentSucceeded.v1" in test_domain._events_and_commands


class TestHandlersForWithExternalEvents:
    """Verify handlers_for() returns PM for events from external streams."""

    def test_handlers_for_internal_event(self, test_domain):
        """handlers_for() should find PM for internal start event."""
        event = OrderPlaced(order_id=str(uuid4()), customer_id="CUST-1", total=100.0)
        handlers = current_domain.handlers_for(event)
        assert CrossDomainPM in handlers

    def test_handlers_for_external_event_stock_reserved(self, test_domain):
        """handlers_for() should find PM for StockReserved via fallback scan.

        External events don't have meta_.part_of set (they're not registered with
        a domain aggregate). handlers_for() falls back to scanning all registered
        stream categories for handlers that match the event's __type__.
        """
        event = StockReserved(
            inventory_item_id="INV-1",
            reservation_id="RES-1",
            order_id="ORD-1",
            quantity=2,
        )
        handlers = current_domain.handlers_for(event)
        assert CrossDomainPM in handlers

    def test_handlers_for_external_event_payment_succeeded(self, test_domain):
        """handlers_for() should also find PM for PaymentSucceeded (second external type)."""
        event = PaymentSucceeded(
            payment_id="PAY-1",
            order_id="ORD-1",
            amount=100.0,
        )
        handlers = current_domain.handlers_for(event)
        assert CrossDomainPM in handlers

    def test_handlers_for_unregistered_external_event(self, test_domain):
        """An external event with no matching handler should not return the PM."""

        class UnhandledExternalEvent(BaseEvent):
            some_field: Identifier()

        test_domain.register_external_event(
            UnhandledExternalEvent, "OtherDomain.UnhandledEvent.v1"
        )

        event = UnhandledExternalEvent(some_field="val-1")
        handlers = current_domain.handlers_for(event)
        # No PM or handler is wired for this event type
        assert CrossDomainPM not in handlers


class TestSyncDispatchWithExternalEvents:
    """Test the sync dispatch path with both internal and external events."""

    def test_sync_dispatch_internal_event_starts_pm(self, test_domain):
        """Order.place() via UoW sync dispatch should start the PM."""
        order = Order.place(customer_id="CUST-1", total=100.0)
        with UnitOfWork():
            current_domain.repository_for(Order).add(order)

        stream_name = f"{CrossDomainPM.meta_.stream_category}-{order.id}"
        messages = test_domain.event_store.store.read(stream_name)
        assert len(messages) == 1

        transition = messages[0].to_domain_object()
        assert transition.state["order_id"] == str(order.id)
        assert transition.state["status"] == "awaiting_reservation"


class TestMessageDispatchWithExternalEvents:
    """Test the Message-based dispatch path for external events.

    This is the ONLY path that works for external events in production (async).
    """

    def _make_message(self, event_cls, event_data, stream_category, stream_id):
        from protean.utils.eventing import (
            DomainMeta,
            MessageEnvelope,
            MessageHeaders,
            Metadata,
        )

        event = event_cls(**event_data)
        headers = MessageHeaders(
            id=f"{stream_category}-{stream_id}-0",
            type=event_cls.__type__,
            stream=f"{stream_category}-{stream_id}",
        )
        envelope = MessageEnvelope.build(event.payload)
        domain_meta = DomainMeta(
            fqn=f"tests.process_manager.test_external_event_dispatch.{event_cls.__name__}",
            kind="EVENT",
            stream_category=stream_category,
            version="v1",
        )
        metadata = Metadata(headers=headers, envelope=envelope, domain=domain_meta)
        return Message(data=event.payload, metadata=metadata)

    def test_external_event_via_message_dispatch(self, test_domain):
        """StockReserved (external) via Message should advance the PM."""
        order_id = str(uuid4())

        # Step 1: Start PM with internal event via Message
        msg1 = self._make_message(
            OrderPlaced,
            {"order_id": order_id, "customer_id": "CUST-1", "total": 100.0},
            "test::order",
            order_id,
        )
        CrossDomainPM._handle(msg1)

        # Step 2: External event via Message
        reservation_id = str(uuid4())
        msg2 = self._make_message(
            StockReserved,
            {
                "inventory_item_id": str(uuid4()),
                "reservation_id": reservation_id,
                "order_id": order_id,
                "quantity": 2,
            },
            "inventory::inventory_item",
            str(uuid4()),
        )
        CrossDomainPM._handle(msg2)

        # Verify PM advanced
        pm_stream = f"{CrossDomainPM.meta_.stream_category}-{order_id}"
        transitions = test_domain.event_store.store.read(pm_stream)
        assert len(transitions) == 2

        final = transitions[-1].to_domain_object()
        assert final.state["status"] == "awaiting_payment"
        assert final.state["reservation_id"] == reservation_id

    def test_full_lifecycle_with_external_events(self, test_domain):
        """Start (internal) → reserve (external) → pay (external) = completed."""
        order_id = str(uuid4())
        reservation_id = str(uuid4())
        payment_id = str(uuid4())

        # Step 1: Start (internal event)
        msg1 = self._make_message(
            OrderPlaced,
            {"order_id": order_id, "customer_id": "CUST-1", "total": 100.0},
            "test::order",
            order_id,
        )
        CrossDomainPM._handle(msg1)

        # Step 2: Stock reserved (external from Inventory)
        msg2 = self._make_message(
            StockReserved,
            {
                "inventory_item_id": str(uuid4()),
                "reservation_id": reservation_id,
                "order_id": order_id,
                "quantity": 2,
            },
            "inventory::inventory_item",
            str(uuid4()),
        )
        CrossDomainPM._handle(msg2)

        # Step 3: Payment succeeded (external from Payments)
        msg3 = self._make_message(
            PaymentSucceeded,
            {
                "payment_id": payment_id,
                "order_id": order_id,
                "amount": 100.0,
            },
            "payments::payment",
            str(uuid4()),
        )
        CrossDomainPM._handle(msg3)

        # Verify full lifecycle
        pm_stream = f"{CrossDomainPM.meta_.stream_category}-{order_id}"
        transitions = test_domain.event_store.store.read(pm_stream)
        assert len(transitions) == 3

        final = transitions[-1].to_domain_object()
        assert final.state["status"] == "completed"
        assert final.state["payment_id"] == payment_id
        assert final.is_complete is True

    def test_mixed_sync_then_message(self, test_domain):
        """Start via UoW sync dispatch, then advance with external Message."""
        # Step 1: Sync dispatch starts PM
        order = Order.place(customer_id="CUST-1", total=100.0)
        with UnitOfWork():
            current_domain.repository_for(Order).add(order)

        # Step 2: External event arrives as Message (async Engine path)
        reservation_id = str(uuid4())
        msg = self._make_message(
            StockReserved,
            {
                "inventory_item_id": str(uuid4()),
                "reservation_id": reservation_id,
                "order_id": str(order.id),
                "quantity": 2,
            },
            "inventory::inventory_item",
            str(uuid4()),
        )
        CrossDomainPM._handle(msg)

        # Verify PM has both transitions
        pm_stream = f"{CrossDomainPM.meta_.stream_category}-{order.id}"
        transitions = test_domain.event_store.store.read(pm_stream)
        assert len(transitions) == 2

        final = transitions[-1].to_domain_object()
        assert final.state["status"] == "awaiting_payment"
        assert final.state["reservation_id"] == reservation_id

    def test_completed_pm_skips_external_events_via_message(self, test_domain):
        """Once a PM is completed, further external events via Message are skipped."""
        order_id = str(uuid4())

        # Complete the full lifecycle
        msg1 = self._make_message(
            OrderPlaced,
            {"order_id": order_id, "customer_id": "CUST-1", "total": 100.0},
            "test::order",
            order_id,
        )
        CrossDomainPM._handle(msg1)

        msg2 = self._make_message(
            StockReserved,
            {
                "inventory_item_id": str(uuid4()),
                "reservation_id": str(uuid4()),
                "order_id": order_id,
                "quantity": 2,
            },
            "inventory::inventory_item",
            str(uuid4()),
        )
        CrossDomainPM._handle(msg2)

        msg3 = self._make_message(
            PaymentSucceeded,
            {
                "payment_id": str(uuid4()),
                "order_id": order_id,
                "amount": 100.0,
            },
            "payments::payment",
            str(uuid4()),
        )
        CrossDomainPM._handle(msg3)

        # PM should be complete now with 3 transitions
        pm_stream = f"{CrossDomainPM.meta_.stream_category}-{order_id}"
        transitions = test_domain.event_store.store.read(pm_stream)
        assert len(transitions) == 3

        # Send another external event — should be skipped
        msg4 = self._make_message(
            PaymentSucceeded,
            {
                "payment_id": str(uuid4()),
                "order_id": order_id,
                "amount": 50.0,
            },
            "payments::payment",
            str(uuid4()),
        )
        CrossDomainPM._handle(msg4)

        # Still only 3 transitions — the 4th was skipped
        transitions = test_domain.event_store.store.read(pm_stream)
        assert len(transitions) == 3

    def test_external_event_message_deserialization_round_trip(self, test_domain):
        """External event Message → dict → Message → to_domain_object() should work."""
        event_data = {
            "inventory_item_id": "INV-1",
            "reservation_id": "RES-1",
            "order_id": "ORD-1",
            "quantity": 2.0,
        }
        msg = self._make_message(
            StockReserved,
            event_data,
            "inventory::inventory_item",
            "INV-1",
        )

        # Simulate Redis round-trip: Message → dict → Message
        msg_dict = msg.to_dict()
        reconstructed = Message.deserialize(msg_dict)

        # Verify type is preserved
        assert reconstructed.metadata.headers.type == "Inventory.StockReserved.v1"

        # Verify to_domain_object() reconstructs the correct event class
        domain_obj = reconstructed.to_domain_object()
        assert domain_obj.__class__.__name__ == "StockReserved"
        assert domain_obj.__class__.__type__ == "Inventory.StockReserved.v1"
        assert domain_obj.order_id == "ORD-1"
        assert domain_obj.reservation_id == "RES-1"

        # Verify the PM handler key matches
        assert domain_obj.__class__.__type__ in CrossDomainPM._handlers
