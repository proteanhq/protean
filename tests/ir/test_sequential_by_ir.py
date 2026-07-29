"""IR extraction of the ``sequential_by`` option (#830, ADR-0028).

The field is sparse: it appears on a handler's IR dict only when set, and
carries the declared value (a field name for event/command handlers, the
boolean opt-in for process managers).
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.ir.builder import IRBuilder
from protean.utils.mixins import handle


class Order(BaseAggregate):
    client_id: String(max_length=50)


class OrderPlaced(BaseEvent):
    order_id: Identifier()
    client_id: String(max_length=50)


class PlaceOrder(BaseCommand):
    order_id: Identifier()
    client_id: String(max_length=50)


class PartitionedOrderHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event):
        pass


class PlainOrderHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event):
        pass


class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def on_place(self, command):
        pass


class OrderPM(BaseProcessManager):
    order_id = Identifier(identifier=True)

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_placed(self, event):
        pass


def _build_ir():
    domain = Domain(name="IRSeq")
    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    domain.register(PlaceOrder, part_of=Order)
    # Same category (order) is partitioned by the PM on order_id, so the event
    # handler on it must agree (one key per category); the command handler is on
    # a separate command category and can use a different key.
    domain.register(PartitionedOrderHandler, part_of=Order, sequential_by="order_id")
    domain.register(PlainOrderHandler, part_of=Order)
    domain.register(OrderCommandHandler, part_of=Order, sequential_by="client_id")
    domain.register(OrderPM, sequential_by=True)
    with domain.domain_context():
        domain.init(traverse=False)
        return IRBuilder(domain).build()


def _order_cluster(ir):
    for cluster in ir["clusters"].values():
        if cluster["aggregate"]["name"] == "Order":
            return cluster
    pytest.fail("Order cluster not found")


@pytest.mark.no_test_domain
class TestSequentialByIR:
    def test_event_handler_carries_sequential_by(self):
        cluster = _order_cluster(_build_ir())
        handlers = cluster["event_handlers"]
        partitioned = next(
            e for e in handlers.values() if e["name"] == "PartitionedOrderHandler"
        )
        assert partitioned["sequential_by"] == "order_id"

    def test_event_handler_omits_when_unset(self):
        cluster = _order_cluster(_build_ir())
        handlers = cluster["event_handlers"]
        plain = next(e for e in handlers.values() if e["name"] == "PlainOrderHandler")
        assert "sequential_by" not in plain

    def test_command_handler_carries_sequential_by(self):
        cluster = _order_cluster(_build_ir())
        ch = next(iter(cluster["command_handlers"].values()))
        assert ch["sequential_by"] == "client_id"

    def test_process_manager_carries_sequential_by(self):
        ir = _build_ir()
        pm = next(iter(ir["flows"]["process_managers"].values()))
        assert pm["sequential_by"] is True
