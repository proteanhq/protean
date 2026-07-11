"""Diagnostics: TestProjectorHandlesOrphanedEvent."""

from protean import Domain, handle
from protean.core.aggregate import BaseAggregate
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _findings,
)


class TestProjectorHandlesOrphanedEvent:
    """PROJECTOR_HANDLES_ORPHANED_EVENT: a projector handling an event that no
    cluster registers is wired to a type that can never be dispatched."""

    def test_orphaned_event_flagged(self):
        domain = Domain(name="Orphan", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderViewProjector:
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        domain.init(traverse=False)

        # A live domain cannot wire a projector to an unregistered event (the
        # ``@handle`` decorator requires a registered event class). The orphan
        # the rule guards — a stale ``__type__`` left after a rename or removal —
        # appears only in materialized IR loaded from an older or hand-edited
        # source, so inject the ghost type into the handler map to exercise it.
        method = next(iter(OrderViewProjector._handlers[OrderPlaced.__type__]))
        OrderViewProjector._handlers["Orphan.RemovedEvent.v1"].add(method)

        ir = IRBuilder(domain).build()

        findings = _findings(ir, "PROJECTOR_HANDLES_ORPHANED_EVENT")
        assert len(findings) > 0
        finding = findings[0]
        assert "OrderViewProjector" in finding["element"]
        assert finding["level"] == "warning"
        # The orphaned type is named; the registered OrderPlaced is not flagged.
        assert "RemovedEvent" in finding["message"]
        assert not any("OrderPlaced" in f["message"] for f in findings)

    def test_internal_aggregate_event_not_flagged(self):
        """An ``internal`` aggregate is excluded from clusters, but its events
        are still registered and dispatchable — a projector handling one is not
        an orphan. The registered-type set must span all registered events, not
        just clustered ones."""

        domain = Domain(name="InternalEvt", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        class InternalTracker(BaseAggregate):
            name = String(max_length=50)

        @domain.event(part_of=InternalTracker)
        class TrackerFired:
            tracker_id = Identifier(identifier=True)

        domain.register(InternalTracker, internal=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderViewProjector:
            @handle(TrackerFired)
            def on_tracker(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "PROJECTOR_HANDLES_ORPHANED_EVENT") == []

    def test_registered_events_not_flagged(self):
        domain = Domain(name="NoOrphan", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(identifier=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderViewProjector:
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

            @handle(OrderShipped)
            def on_shipped(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "PROJECTOR_HANDLES_ORPHANED_EVENT") == []

    def test_cross_aggregate_registered_event_not_flagged(self):
        """A projector legitimately handles events from other aggregates; the
        registered-type lookup spans all clusters, so a foreign-but-registered
        event is not an orphan."""
        domain = Domain(name="CrossAgg", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.aggregate
        class Payment:
            name = String(max_length=50)

        @domain.event(part_of=Payment)
        class PaymentReceived:
            payment_id = Identifier(identifier=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderViewProjector:
            @handle(PaymentReceived)
            def on_payment(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "PROJECTOR_HANDLES_ORPHANED_EVENT") == []
