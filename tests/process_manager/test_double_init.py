"""Regression test: calling domain.init() twice on a domain with a process manager.

The first init() generates a transition event (e.g. _OrderFulfillmentPMTransition)
whose part_of points to the PM class.  On the second init(),
_assign_aggregate_clusters tried to walk up part_of until it found a
BaseAggregate — but BaseProcessManager is not a BaseAggregate, so the loop
crashed with ``AttributeError: 'Options' object has no attribute 'part_of'``.
"""

import pytest

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


def test_double_init_with_process_manager(test_domain):
    """Calling init() twice must not crash on PM transition events."""
    test_domain.init(traverse=False)
    # Second init should not raise AttributeError
    test_domain.init(traverse=False)
