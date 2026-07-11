"""Diagnostics: TestCommandHandlerCrossCluster."""

from protean import Domain, handle
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _findings,
)


class TestCommandHandlerCrossCluster:
    """COMMAND_HANDLER_CROSS_CLUSTER: a command handler processing another
    cluster's command puts that aggregate's write path outside its boundary."""

    def test_cross_cluster_command_flagged(self):
        domain = Domain(name="CrossCluster", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.aggregate
        class Shipment:
            name = String(max_length=50)

        @domain.command(part_of=Order)
        class PlaceOrder:
            order_id = Identifier(identifier=True)

        @domain.command(part_of=Shipment)
        class DispatchShipment:
            shipment_id = Identifier(identifier=True)

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def place(self, command):
                pass

        domain.init(traverse=False)

        # The framework forbids a command handler from targeting another
        # cluster's command (handler_setup validates command/handler part_of
        # equality), so this cannot come from registration. It can appear in
        # materialized IR loaded from an older or hand-edited source — the state
        # the diagnostic guards — so inject the foreign command type into the
        # handler map to exercise that path.
        method = next(iter(OrderCommandHandler._handlers[PlaceOrder.__type__]))
        OrderCommandHandler._handlers[DispatchShipment.__type__].add(method)

        ir = IRBuilder(domain).build()

        findings = _findings(ir, "COMMAND_HANDLER_CROSS_CLUSTER")
        assert len(findings) > 0
        finding = findings[0]
        assert "OrderCommandHandler" in finding["element"]
        assert finding["level"] == "warning"
        # Pin the cluster *attribution*, not just any "Order"/"Shipment"
        # substring (the handler name and command type contain those already):
        # the message must name both distinct cluster FQNs — the handler's own
        # cluster and the command's owning cluster.
        order_cluster = next(k for k in ir["clusters"] if k.endswith(".Order"))
        shipment_cluster = next(k for k in ir["clusters"] if k.endswith(".Shipment"))
        assert order_cluster != shipment_cluster
        assert order_cluster in finding["message"]
        assert shipment_cluster in finding["message"]

    def test_same_cluster_command_not_flagged(self):
        domain = Domain(name="SameCluster", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.command(part_of=Order)
        class PlaceOrder:
            order_id = Identifier(identifier=True)

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def place(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "COMMAND_HANDLER_CROSS_CLUSTER") == []

    def test_unregistered_command_type_skipped(self):
        """A command type in the handler map but registered in no cluster is
        attributable to no owner and must be skipped, not flagged."""
        domain = Domain(name="UnregisteredCmd", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.command(part_of=Order)
        class PlaceOrder:
            order_id = Identifier(identifier=True)

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def place(self, command):
                pass

        domain.init(traverse=False)

        # Inject a command type owned by no registered cluster.
        method = next(iter(OrderCommandHandler._handlers[PlaceOrder.__type__]))
        OrderCommandHandler._handlers["Ghost.Unknown.v1"].add(method)

        ir = IRBuilder(domain).build()

        assert _findings(ir, "COMMAND_HANDLER_CROSS_CLUSTER") == []

    def test_cross_cluster_event_handler_not_flagged(self):
        """An event handler reacting across clusters is legitimate (the #824
        boundary); the command-only rule must ignore event handlers."""
        domain = Domain(name="EventCross", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.aggregate
        class Shipment:
            name = String(max_length=50)

        @domain.event(part_of=Shipment)
        class ShipmentDispatched:
            shipment_id = Identifier(identifier=True)

        @domain.event_handler(part_of=Order)
        class OrderReactsToShipment:
            @handle(ShipmentDispatched)
            def on_dispatched(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "COMMAND_HANDLER_CROSS_CLUSTER") == []
