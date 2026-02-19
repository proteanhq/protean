"""Tests for process manager registration via decorator and manual registration."""

import pytest

from protean.core.process_manager import BaseProcessManager
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Identifier, String
from protean.utils import fully_qualified_name
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


def test_base_process_manager_cannot_be_instantiated():
    with pytest.raises(NotSupportedError):
        BaseProcessManager()


def test_registering_a_process_manager_manually(test_domain):
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=[
            "test::order",
            "test::payment",
            "test::shipping",
        ],
    )
    test_domain.init(traverse=False)

    assert (
        fully_qualified_name(OrderFulfillmentPM)
        in test_domain.registry.process_managers
    )


def test_registering_a_process_manager_via_decorator(test_domain):
    @test_domain.process_manager(
        stream_categories=[
            "test::order",
            "test::payment",
        ]
    )
    class SimplePM:
        order_id: Identifier()
        status: String(default="new")

        @handle(OrderPlaced, start=True, correlate="order_id")
        def on_order_placed(self, event: OrderPlaced) -> None:
            self.order_id = event.order_id
            self.status = "started"

    test_domain.init(traverse=False)

    assert fully_qualified_name(SimplePM) in test_domain.registry.process_managers


def test_process_manager_requires_at_least_one_start_handler(test_domain):
    class BadPM(BaseProcessManager):
        order_id: Identifier()

        @handle(OrderPlaced, correlate="order_id")
        def on_order_placed(self, event: OrderPlaced) -> None:
            pass

    test_domain.register(
        BadPM,
        stream_categories=["test::order"],
    )

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)

    assert "must have at least one handler with `start=True`" in str(exc.value)


def test_process_manager_requires_correlate_on_handlers(test_domain):
    class BadPM(BaseProcessManager):
        order_id: Identifier()

        @handle(OrderPlaced, start=True)
        def on_order_placed(self, event: OrderPlaced) -> None:
            pass

    test_domain.register(
        BadPM,
        stream_categories=["test::order"],
    )

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)

    assert "must specify a `correlate` parameter" in str(exc.value)


def test_process_manager_handler_must_target_events(test_domain):
    class BadPM(BaseProcessManager):
        order_id: Identifier()

        @handle("not_a_class", start=True, correlate="order_id")
        def on_something(self, event) -> None:
            pass

    test_domain.register(
        BadPM,
        stream_categories=["test::order"],
    )

    with pytest.raises(IncorrectUsageError) as exc:
        test_domain.init(traverse=False)

    assert "is not associated with an event" in str(exc.value)


def test_process_manager_options(test_domain):
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=[
            "test::order",
            "test::payment",
            "test::shipping",
        ],
    )
    test_domain.init(traverse=False)

    assert OrderFulfillmentPM.meta_.stream_categories == [
        "test::order",
        "test::payment",
        "test::shipping",
    ]
    assert "order_fulfillment_pm" in OrderFulfillmentPM.meta_.stream_category


def test_process_manager_stream_categories_inferred_from_events(test_domain):
    """When no stream_categories is specified, they are inferred from handled events' aggregates."""

    class InferredPM(BaseProcessManager):
        order_id: Identifier()

        @handle(OrderPlaced, start=True, correlate="order_id")
        def on_order_placed(self, event: OrderPlaced) -> None:
            self.order_id = event.order_id

        @handle(PaymentConfirmed, correlate="order_id")
        def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
            pass

    test_domain.register(InferredPM)
    test_domain.init(traverse=False)

    # Stream categories should be inferred from the Order and Payment aggregates
    assert len(InferredPM.meta_.stream_categories) > 0


def test_process_manager_appears_in_registry(test_domain):
    test_domain.register(
        OrderFulfillmentPM,
        stream_categories=["test::order", "test::payment", "test::shipping"],
    )
    test_domain.init(traverse=False)

    assert len(test_domain.registry.process_managers) == 1
