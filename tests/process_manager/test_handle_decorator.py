"""Tests for the extended @handle decorator with start, correlate, and end parameters."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.fields import Identifier, String
from protean.utils.mixins import handle

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


def test_handle_decorator_preserves_start_attribute(test_domain):
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)

    # Find the start handler
    for event_type, handlers in OrderFulfillmentPM._handlers.items():
        for handler_method in handlers:
            if handler_method.__name__ == "on_order_placed":
                assert getattr(handler_method, "_start", False) is True
            elif handler_method.__name__ == "on_payment_confirmed":
                assert getattr(handler_method, "_start", False) is False


def test_handle_decorator_preserves_correlate_attribute(test_domain):
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)

    for event_type, handlers in OrderFulfillmentPM._handlers.items():
        for handler_method in handlers:
            assert getattr(handler_method, "_correlate", None) == "order_id"


def test_handle_decorator_preserves_end_attribute(test_domain):
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)

    for event_type, handlers in OrderFulfillmentPM._handlers.items():
        for handler_method in handlers:
            if handler_method.__name__ == "on_payment_failed":
                assert getattr(handler_method, "_end", False) is True
            elif handler_method.__name__ == "on_order_placed":
                assert getattr(handler_method, "_end", False) is False


def test_handle_decorator_backward_compat_with_event_handlers(test_domain):
    """Existing event handlers that use @handle without PM params should work unchanged."""

    class UserRegistered(BaseEvent):
        user_id: Identifier()

    class User(BaseAggregate):
        name: String()

    class UserEventHandlers(BaseEventHandler):
        @handle(UserRegistered)
        def on_registered(self, event: UserRegistered) -> None:
            pass

    test_domain.register(User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserEventHandlers, part_of=User)
    test_domain.init(traverse=False)

    # Ensure the handler was registered correctly
    assert UserRegistered.__type__ in UserEventHandlers._handlers

    # Ensure the PM-specific attributes default correctly
    handler_method = next(iter(UserEventHandlers._handlers[UserRegistered.__type__]))
    assert getattr(handler_method, "_start", False) is False
    assert getattr(handler_method, "_correlate", None) is None
    assert getattr(handler_method, "_end", False) is False


def test_handlers_recorded_in_process_manager(test_domain):
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)

    # Should have 4 handlers (OrderPlaced, PaymentConfirmed, PaymentFailed, ShipmentDelivered)
    assert len(OrderFulfillmentPM._handlers) == 4


def test_handle_with_dict_correlate():
    """Verify that dict-style correlate is accepted and stored."""

    class SomeEvent(BaseEvent):
        ext_order_id: Identifier()

    class DictCorrelatePM(BaseProcessManager):
        my_order_id: Identifier()

        @handle(SomeEvent, start=True, correlate={"my_order_id": "ext_order_id"})
        def on_something(self, event: SomeEvent) -> None:
            pass

    # Verify the correlate attribute is stored as a dict
    handler_method = DictCorrelatePM.on_something
    assert getattr(handler_method, "_correlate", None) == {
        "my_order_id": "ext_order_id"
    }
