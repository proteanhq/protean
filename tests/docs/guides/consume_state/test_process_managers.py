"""Check what docs/guides/consume-state/process-managers.md says process managers do.

Each test loads its example fresh, so every test gets its own domain, its own
event classes and its own memory event store. ``register_external_event()``
sets ``__type__`` on the event class it is given, and a fresh load builds new
classes, so one test's registration never leaks into another.

Events are handed to the process manager with ``_handle()``, the way the engine
delivers them, and the test reads the transitions the process manager wrote to
its own stream.
"""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def activated(module):
    module.domain.init(traverse=False)
    return module.domain.domain_context()


@pytest.fixture
def lifecycle_example():
    module = load_example("guides/consume-state/process-managers/001.py")
    with activated(module):
        yield module


@pytest.fixture
def commands_example():
    module = load_example("guides/consume-state/process-managers/003.py")
    with activated(module):
        yield module


@pytest.fixture
def external_example():
    module = load_example("guides/consume-state/process-managers/004.py")
    with activated(module):
        yield module


def transitions(module, pm_cls, order_id):
    stream = f"{pm_cls.meta_.stream_category}-{order_id}"
    return [
        message.to_domain_object()
        for message in module.domain.event_store.store.read(stream)
    ]


def statuses(module, pm_cls, order_id):
    return [t.state["status"] for t in transitions(module, pm_cls, order_id)]


def commands_for(module, aggregate_cls, order_id):
    """The commands for ``order_id`` written to the aggregate's command streams."""
    prefix = f"{aggregate_cls.meta_.stream_category}:command-"
    commands = [
        message.to_domain_object()
        for message in module.domain.event_store.store.read("$all")
        if message.metadata.headers.stream.startswith(prefix)
    ]
    return [command for command in commands if command.order_id == order_id]


class TestDefiningAProcessManager:
    def test_order_moves_from_payment_to_shipment_to_completed(self, lifecycle_example):
        ex = lifecycle_example
        pm = ex.OrderFulfillmentPM

        pm._handle(ex.OrderPlaced(order_id="ord-1", customer_id="c-1", total=50.0))
        pm._handle(
            ex.PaymentConfirmed(payment_id="pay-1", order_id="ord-1", amount=50.0)
        )
        pm._handle(ex.ShipmentDelivered(order_id="ord-1"))

        steps = transitions(ex, pm, "ord-1")
        assert [t.state["status"] for t in steps] == [
            "awaiting_payment",
            "awaiting_shipment",
            "completed",
        ]
        assert [t.handler_name for t in steps] == [
            "on_order_placed",
            "on_payment_confirmed",
            "on_shipment_delivered",
        ]
        assert steps[1].state["payment_id"] == "pay-1"
        assert [t.is_complete for t in steps] == [False, False, True]

    def test_end_true_completes_the_process_on_payment_failure(self, lifecycle_example):
        ex = lifecycle_example
        pm = ex.OrderFulfillmentPM

        pm._handle(ex.OrderPlaced(order_id="ord-2", customer_id="c-1", total=50.0))
        pm._handle(
            ex.PaymentFailed(payment_id="pay-2", order_id="ord-2", reason="declined")
        )

        steps = transitions(ex, pm, "ord-2")
        assert steps[-1].state["status"] == "cancelled"
        assert steps[-1].is_complete is True

    def test_a_completed_process_skips_later_events(self, lifecycle_example):
        ex = lifecycle_example
        pm = ex.OrderFulfillmentPM

        pm._handle(ex.OrderPlaced(order_id="ord-3", customer_id="c-1", total=50.0))
        pm._handle(
            ex.PaymentFailed(payment_id="pay-3", order_id="ord-3", reason="declined")
        )
        pm._handle(
            ex.PaymentConfirmed(payment_id="pay-3", order_id="ord-3", amount=50.0)
        )

        assert statuses(ex, pm, "ord-3") == ["awaiting_payment", "cancelled"]

    def test_a_non_start_event_without_a_process_is_skipped(self, lifecycle_example):
        ex = lifecycle_example
        pm = ex.OrderFulfillmentPM

        pm._handle(ex.ShipmentDelivered(order_id="ord-unknown"))

        assert statuses(ex, pm, "ord-unknown") == []


class TestIssuingCommands:
    def test_order_placed_issues_request_payment_for_the_order_total(
        self, commands_example
    ):
        ex = commands_example

        ex.OrderPaymentPM._handle(
            ex.OrderPlaced(order_id="ord-1", customer_id="c-1", total=75.0)
        )

        assert statuses(ex, ex.OrderPaymentPM, "ord-1") == ["awaiting_payment"]
        [command] = commands_for(ex, ex.Payment, "ord-1")
        assert isinstance(command, ex.RequestPayment)
        assert command.order_id == "ord-1"
        assert command.amount == 75.0

    def test_payment_failure_cancels_the_order_and_ends_the_process(
        self, commands_example
    ):
        ex = commands_example

        ex.OrderPaymentPM._handle(
            ex.OrderPlaced(order_id="ord-2", customer_id="c-1", total=75.0)
        )
        ex.OrderPaymentPM._handle(
            ex.PaymentFailed(payment_id="pay-2", order_id="ord-2", reason="declined")
        )

        steps = transitions(ex, ex.OrderPaymentPM, "ord-2")
        assert steps[-1].state["status"] == "cancelled"
        assert steps[-1].is_complete is True
        [command] = commands_for(ex, ex.Order, "ord-2")
        assert isinstance(command, ex.CancelOrder)
        assert command.order_id == "ord-2"


class TestHandlingEventsFromOtherDomains:
    @pytest.mark.parametrize(
        ("type_string", "class_name"),
        [
            ("Billing.PaymentReceived.v1", "PaymentReceived"),
            ("Inventory.InventoryReserved.v1", "InventoryReserved"),
            ("Inventory.InventoryUnavailable.v1", "InventoryUnavailable"),
        ],
    )
    def test_external_event_resolves_by_its_type_string(
        self, external_example, type_string, class_name
    ):
        ex = external_example
        event_cls = getattr(ex, class_name)

        assert ex.domain._events_and_commands[type_string] is event_cls
        assert event_cls.__type__ == type_string
        assert type_string in ex.OrderFulfillmentPM._handlers

    def test_order_completes_when_payment_then_inventory_arrive(self, external_example):
        ex = external_example
        pm = ex.OrderFulfillmentPM

        pm._handle(ex.OrderPlaced(order_id="ord-1", customer_id="c-1", total=20.0))
        pm._handle(
            ex.PaymentReceived(payment_id="pay-1", order_id="ord-1", amount=20.0)
        )
        pm._handle(ex.InventoryReserved(order_id="ord-1", product_id="sku-1"))

        steps = transitions(ex, pm, "ord-1")
        assert [t.state["status"] for t in steps] == [
            "awaiting_payment",
            "awaiting_inventory",
            "completed",
        ]
        assert steps[-1].is_complete is True
        [command] = commands_for(ex, ex.Order, "ord-1")
        assert isinstance(command, ex.ReserveInventory)
        assert command.order_id == "ord-1"

    def test_inventory_reserved_before_payment_does_not_complete(
        self, external_example
    ):
        ex = external_example
        pm = ex.OrderFulfillmentPM

        pm._handle(ex.OrderPlaced(order_id="ord-2", customer_id="c-1", total=20.0))
        pm._handle(ex.InventoryReserved(order_id="ord-2", product_id="sku-1"))
        pm._handle(
            ex.PaymentReceived(payment_id="pay-2", order_id="ord-2", amount=20.0)
        )

        steps = transitions(ex, pm, "ord-2")
        assert [t.state["status"] for t in steps] == [
            "awaiting_payment",
            "awaiting_payment",
            "awaiting_inventory",
        ]
        assert [t.is_complete for t in steps] == [False, False, False]

    def test_inventory_unavailable_ends_the_process(self, external_example):
        ex = external_example
        pm = ex.OrderFulfillmentPM

        pm._handle(ex.OrderPlaced(order_id="ord-3", customer_id="c-1", total=20.0))
        pm._handle(ex.InventoryUnavailable(order_id="ord-3", product_id="sku-1"))

        steps = transitions(ex, pm, "ord-3")
        assert steps[-1].state["status"] == "inventory_unavailable"
        assert steps[-1].is_complete is True
