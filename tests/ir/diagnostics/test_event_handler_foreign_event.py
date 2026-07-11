"""Diagnostics: EVENT_HANDLER_FOREIGN_EVENT (cross-cluster event handling)."""

from protean import Domain, handle
from protean.fields import Identifier
from protean.fields.simple import Float, String
from protean.ir.builder import IRBuilder
from protean.utils import fqn


class TestEventHandlerForeignEvent:
    """EVENT_HANDLER_FOREIGN_EVENT flags an event handler whose ``part_of``
    cluster differs from the cluster that owns an event it handles. Scope is
    ``event_handlers`` only — projectors and process managers are excluded by
    construction."""

    def test_foreign_event_flagged(self):
        domain = Domain(name="FEBasic", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Fulfillment:
            status = String(max_length=20)

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(required=True)

        @domain.event_handler(part_of=Fulfillment)
        class FulfillmentHandler:
            @handle(OrderShipped)
            def on_order_shipped(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "EVENT_HANDLER_FOREIGN_EVENT"
        ]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(FulfillmentHandler)
        assert d["level"] == "warning"
        # #774 schema
        assert d["category"] == "handler_completeness"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]
        # Pin the owner-vs-handler direction: the handler's own cluster is
        # named via "part_of", the event's owning cluster is named via
        # "owned by cluster" — swapping them must fail this assertion.
        assert "FulfillmentHandler (part_of Fulfillment)" in d["message"]
        assert "owned by cluster Order" in d["message"]

    def test_two_foreign_events_yield_two_findings(self):
        """A handler handling two foreign events (from two different clusters)
        produces two findings — one per handled foreign ``__type__`` — and a
        same-cluster event it also handles produces none."""
        domain = Domain(name="FEMulti", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Payment:
            amount = Float()

        @domain.aggregate
        class Fulfillment:
            status = String(max_length=20)

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(required=True)

        @domain.event(part_of=Payment)
        class PaymentCaptured:
            payment_id = Identifier(required=True)

        @domain.event(part_of=Fulfillment)
        class FulfillmentStarted:
            order_id = Identifier(required=True)

        @domain.event_handler(part_of=Fulfillment)
        class FulfillmentHandler:
            @handle(OrderShipped)
            def on_order_shipped(self, event):
                pass

            @handle(PaymentCaptured)
            def on_payment_captured(self, event):
                pass

            @handle(FulfillmentStarted)
            def on_fulfillment_started(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "EVENT_HANDLER_FOREIGN_EVENT"
        ]
        assert len(diags) == 2
        messages = " ".join(d["message"] for d in diags)
        assert "OrderShipped" in messages
        assert "PaymentCaptured" in messages
        assert "FulfillmentStarted" not in messages

    def test_same_cluster_handling_not_flagged(self):
        domain = Domain(name="FESame", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(required=True)

        @domain.event_handler(part_of=Order)
        class OrderHandler:
            @handle(OrderShipped)
            def on_order_shipped(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes

    def test_projector_out_of_scope(self):
        """A projector consuming ANOTHER cluster's event is compliant by
        design — this rule reads only ``event_handlers``, never projectors.
        The projector here is ``part_of`` neither cluster and handles
        ``Fulfillment``'s event, so if projectors were ever pulled into the
        scan by mistake this test would catch it; a same-cluster projector
        would pass vacuously even with a scope bug."""
        domain = Domain(name="FEProjector", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Fulfillment:
            status = String(max_length=20)

        @domain.event(part_of=Fulfillment)
        class FulfillmentStarted:
            order_id = Identifier(required=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)
            status = String(max_length=20)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderProjector:
            @handle(FulfillmentStarted)
            def on_fulfillment_started(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes

    def test_process_manager_out_of_scope(self):
        """A process manager coordinating two clusters' events is compliant
        by design — this rule never reads ``ir["flows"]``."""
        domain = Domain(name="FEPm", root_path=".")

        @domain.event(part_of="FlowOrder")
        class FlowOrderPlaced:
            order_id = Identifier(required=True)

        @domain.event(part_of="FlowPayment")
        class FlowPaymentConfirmed:
            order_id = Identifier(required=True)
            payment_id = Identifier(required=True)

        @domain.aggregate
        class FlowOrder:
            total = Float(default=0.0)

        @domain.aggregate
        class FlowPayment:
            amount = Float(default=0.0)

        @domain.process_manager(stream_categories=["flow_order", "flow_payment"])
        class OrderFulfillmentFlow:
            order_id = Identifier()

            @handle(FlowOrderPlaced, start=True, correlate="order_id")
            def on_order_placed(self, event):
                pass

            @handle(FlowPaymentConfirmed, correlate="order_id", end=True)
            def on_payment_confirmed(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes

    def test_orphaned_event_type_not_flagged(self):
        """A handled ``__type__`` owned by no cluster in this domain (here, an
        event that belongs to an entirely different domain) is not flagged —
        there is no owning cluster to compare against, and no other rule in
        the tree currently covers this shape either."""
        other_domain = Domain(name="FEOrphanSource", root_path=".")

        @other_domain.aggregate
        class OtherAggregate:
            name = String(max_length=20)

        @other_domain.event(part_of=OtherAggregate)
        class ExternalEvent:
            other_id = Identifier(required=True)

        other_domain.init(traverse=False)

        domain = Domain(name="FEOrphan", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.event_handler(part_of=Order)
        class OrderHandler:
            @handle(ExternalEvent)
            def on_external(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes

    def test_colliding_type_names_do_not_flag_compliant_code(self):
        """``__type__`` encodes only the domain and class name
        (``DomainName.ClassName.vN``), not the owning aggregate — so two
        distinct event classes named identically in different clusters of
        the same domain collide onto one ``__type__`` key. A handler that
        compliantly handles its own cluster's event must not be falsely
        flagged as foreign just because another cluster happens to have a
        same-named event; an ambiguous owner is treated like an orphan
        (never flagged), not resolved to whichever cluster iterated last."""
        domain = Domain(name="FECollision", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Fulfillment:
            status = String(max_length=20)

        @domain.event(part_of=Order)
        class OrderCreated:
            order_id = Identifier(required=True)

        @domain.event(part_of=Fulfillment)
        class FulfillmentCreated:
            fulfillment_id = Identifier(required=True)

        # Force a __type__ collision without wiping either registry entry:
        # fqn() (used as the registry/cluster key) reads __qualname__, but
        # __type__ is built from __name__ alone, so the two stay distinct
        # in the registry while colliding onto one __type__ key.
        FulfillmentCreated.__name__ = "OrderCreated"

        @domain.event_handler(part_of=Fulfillment)
        class FulfillmentHandler:
            @handle(FulfillmentCreated)
            def on_created(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        order_events = ir["clusters"][fqn(Order)]["events"]
        fulfillment_events = ir["clusters"][fqn(Fulfillment)]["events"]
        assert len(order_events) == 1
        assert len(fulfillment_events) == 1
        order_type = next(iter(order_events.values()))["__type__"]
        fulfillment_type = next(iter(fulfillment_events.values()))["__type__"]
        assert order_type == fulfillment_type, "test setup must collide __type__"

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes

    def test_command_handler_never_flagged(self):
        """Disjointness with command handlers: this rule reads only
        ``event_handlers``, so a command handler must never appear under
        ``EVENT_HANDLER_FOREIGN_EVENT`` even in a domain that also has a
        genuinely cross-cluster event handler.

        (A cross-cluster *command* handler cannot be constructed here — the
        framework's ``_validate_command_handler_method`` already rejects a
        command handler whose command belongs to a different aggregate, i.e.
        ``COMMAND_HANDLER_CROSS_CLUSTER`` from #777 is unreachable at this
        point in the tree. The command handler below is same-cluster, which
        is the only shape the framework allows; the assertion that matters is
        that it never appears under our rule's findings.)
        """
        domain = Domain(name="FEDisjoint", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Fulfillment:
            status = String(max_length=20)

        @domain.command(part_of=Order)
        class ShipOrder:
            order_id = Identifier(required=True)

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(required=True)

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(ShipOrder)
            def handle_ship_order(self, command):
                pass

        @domain.event_handler(part_of=Fulfillment)
        class FulfillmentEventHandler:
            @handle(OrderShipped)
            def on_order_shipped(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "EVENT_HANDLER_FOREIGN_EVENT"
        ]
        assert len(diags) == 1
        assert diags[0]["element"] == fqn(FulfillmentEventHandler)
        assert diags[0]["element"] != fqn(OrderCommandHandler)

    def test_event_without_type_is_skipped_from_ownership(self):
        """An event carrying no ``__type__`` contributes no ownership entry, so
        a handler handling it has nothing to compare against and is not flagged.
        Exercises the ``if not event_type`` guard in the ownership scan — a real
        event always carries a ``__type__``, so the typeless entry is forced by
        clearing it on the built IR before re-running the diagnostic."""
        domain = Domain(name="FENoType", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Fulfillment:
            status = String(max_length=20)

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(required=True)

        @domain.event_handler(part_of=Fulfillment)
        class FulfillmentHandler:
            @handle(OrderShipped)
            def on_order_shipped(self, event):
                pass

        domain.init(traverse=False)
        builder = IRBuilder(domain)
        ir = builder.build()

        # Sanity: with an intact __type__ this is a genuine foreign-event finding.
        assert any(
            d["code"] == "EVENT_HANDLER_FOREIGN_EVENT" for d in ir["diagnostics"]
        )

        # Strip __type__ from Order's event so it registers no owner.
        for event in ir["clusters"][fqn(Order)]["events"].values():
            event["__type__"] = None

        builder._diagnostics = []
        builder._diagnose_event_handler_foreign_event(ir)

        codes = [d["code"] for d in builder._diagnostics]
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes

    def test_suppress_checks_drops_finding(self):
        domain = Domain(name="FESuppress", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Fulfillment:
            status = String(max_length=20)

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(required=True)

        @domain.event_handler(
            part_of=Fulfillment, suppress_checks=["EVENT_HANDLER_FOREIGN_EVENT"]
        )
        class FulfillmentHandler:
            @handle(OrderShipped)
            def on_order_shipped(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "EVENT_HANDLER_FOREIGN_EVENT" not in codes

    def test_suppressions_allow_list_grandfathers_first(self):
        domain = Domain(name="FEAllowList", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Payment:
            amount = Float()

        @domain.aggregate
        class Fulfillment:
            status = String(max_length=20)

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(required=True)

        @domain.event(part_of=Payment)
        class PaymentCaptured:
            payment_id = Identifier(required=True)

        @domain.event_handler(part_of=Fulfillment)
        class FulfillmentHandler:
            @handle(OrderShipped)
            def on_order_shipped(self, event):
                pass

            @handle(PaymentCaptured)
            def on_payment_captured(self, event):
                pass

        domain.config["lint"] = {"suppressions": {"EVENT_HANDLER_FOREIGN_EVENT": 1}}
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "EVENT_HANDLER_FOREIGN_EVENT"
        ]
        assert len(diags) == 1
