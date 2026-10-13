"""The examples on ``docs/reference/server/sequential-by.md`` behave as the page says."""

import pytest

from protean import handle
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier
from protean.port.broker import BrokerCapabilities
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_each_handler_kind_keeps_its_sequential_by():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.init(traverse=False)

    assert example.OrderEventHandler.meta_.sequential_by == "client_id"
    assert example.ProductSummaryProjector.meta_.sequential_by == "product_id"
    assert example.OrderFulfillment.meta_.sequential_by is True


def test_each_category_is_partitioned_by_the_key_its_handler_names():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.init(traverse=False)

    assert example.domain._partition_keys == {
        "shop::order": "client_id",
        "shop::product": "product_id",
        # The process manager's ``correlate="order_id"`` field.
        "shop::payment": "order_id",
    }


def test_the_inline_broker_keeps_an_ordinary_subscription():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        engine = Engine(example.domain, test_mode=True)

    module = example.OrderFulfillment.__module__
    # No ``-partitioned`` subscription: under the inline broker the process
    # manager gets one plain subscription per category.
    assert f"{module}.OrderFulfillment-partitioned" not in engine.subscriptions
    assert isinstance(
        engine.subscriptions[f"{module}.OrderFulfillment-shop::payment"],
        EventStoreSubscription,
    )


def test_a_key_the_event_does_not_carry_fails_at_init():
    example = load_example("reference/server/sequential-by/001.py")
    example.OrderEventHandler.meta_.sequential_by = "region"

    with pytest.raises(
        IncorrectUsageError,
        match="Event `OrderPlaced` has no field named `region`",
    ):
        example.domain.init(traverse=False)


def test_a_process_manager_event_without_its_correlate_field_fails_at_init():
    example = load_example("reference/server/sequential-by/001.py")

    @example.domain.event(part_of=example.Payment)
    class PaymentRefunded:
        payment_id = Identifier(required=True)

    @example.domain.process_manager(sequential_by=True)
    class Refunds:
        payment_id = Identifier(identifier=True)

        @handle(PaymentRefunded, start=True, correlate="order_id")
        def on_refunded(self, event: PaymentRefunded) -> None: ...

    with pytest.raises(
        IncorrectUsageError,
        match="Event `PaymentRefunded` has no field named `order_id`",
    ):
        example.domain.init(traverse=False)


def test_two_keys_on_one_category_fail_at_init():
    example = load_example("reference/server/sequential-by/001.py")

    # The clash the page names: the ``client_id`` handler and a process manager
    # that correlates ``OrderPlaced`` by ``order_id``.
    @example.domain.process_manager(sequential_by=True)
    class OrderTracking:
        order_id = Identifier(identifier=True)

        @handle(example.OrderPlaced, start=True, correlate="order_id")
        def on_placed(self, event) -> None: ...

    with pytest.raises(
        IncorrectUsageError,
        match="`shop::order` is partitioned by conflicting keys",
    ):
        example.domain.init(traverse=False)


def test_the_boolean_form_is_rejected_on_an_event_handler():
    example = load_example("reference/server/sequential-by/001.py")
    example.OrderEventHandler.meta_.sequential_by = True

    with pytest.raises(IncorrectUsageError, match="for process managers only"):
        example.domain.init(traverse=False)


class _BrokerWithoutPartitioning:
    """A stand-in for a non-inline broker that lacks ``STREAM_PARTITIONING``.

    It carries only what the capability check reads: a name and
    ``has_capability``.
    """

    name = "default"

    def has_capability(self, capability: BrokerCapabilities) -> bool:
        return capability != BrokerCapabilities.STREAM_PARTITIONING


def test_a_broker_without_partitioning_is_rejected():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.init(traverse=False)
    example.domain.brokers._brokers["default"] = _BrokerWithoutPartitioning()

    with pytest.raises(
        IncorrectUsageError, match="does not advertise STREAM_PARTITIONING"
    ):
        example.domain._handler_configurator.validate_sequential_by_capabilities()
