"""Tests for the ``method_edges`` derivation post-pass (#1433).

The builder materializes two behavioral edges into the IR: ``raises`` (which
event FQNs an aggregate or entity method raises) and ``invokes`` (which element
method a handler method calls). Both are read from method bodies through the
behavioral view, so the fixtures live in an on-disk module
(``tests/ir/support/method_edges_domain.py``) whose source the view can parse.
"""

import jsonschema
import pytest

from protean import Domain, handle
from protean.core.aggregate import BaseAggregate
from protean.fields import Identifier, String
from protean.ir import load_schema
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.support import method_edges_domain as m

pytestmark = pytest.mark.no_test_domain


def _build_domain() -> Domain:
    """Register the whole method-edges fixture cluster onto a fresh domain."""
    domain = Domain(name="MethodEdges", root_path=".")
    domain.register(m.Order)
    domain.register(m.OrderLine, part_of=m.Order)
    domain.register(m.OrderTag, part_of=m.Order)
    for event in (
        m.OrderPlaced,
        m.OrderCancelled,
        m.OrderShipped,
        m.OrderDelivered,
        m.OrderRegistered,
        m.LineAdjusted,
    ):
        domain.register(event, part_of=m.Order)
    domain.register(m.PlaceOrder, part_of=m.Order)
    domain.register(m.TouchOrder, part_of=m.Order)
    domain.register(m.OrderCommandHandler, part_of=m.Order)
    domain.register(m.OrderNotifier, part_of=m.Order)
    domain.register(m.OrderProcess)
    domain.register(m.OrderView)
    domain.register(
        m.OrderViewProjector, projector_for=m.OrderView, aggregates=[m.Order]
    )
    domain.register(m.Catalog)
    domain.init(traverse=False)
    return domain


@pytest.fixture
def ir() -> dict:
    return IRBuilder(_build_domain()).build()


def _fq(name: str) -> str:
    return f"tests.ir.support.method_edges_domain.{name}"


class TestRaises:
    """``raises`` is derived by co-location on aggregates and entities."""

    def test_self_rooted_raise_records_the_event(self, ir):
        agg = ir["clusters"][_fq("Order")]["aggregate"]
        assert agg["method_edges"]["place"] == {"raises": [_fq("OrderPlaced")]}

    def test_factory_idiom_raise_records_the_event(self, ir):
        # ``order.raise_(...)`` in a classmethod: the receiver role is UNKNOWN,
        # but the derivation keys on the called method name, so it still counts.
        agg = ir["clusters"][_fq("Order")]["aggregate"]
        assert agg["method_edges"]["register_new"] == {
            "raises": [_fq("OrderRegistered")]
        }

    def test_two_events_built_one_raised_records_both(self, ir):
        # Pins the documented over-report: the method builds OrderShipped and
        # OrderDelivered and raises only one, but both are recorded.
        agg = ir["clusters"][_fq("Order")]["aggregate"]
        assert agg["method_edges"]["split"] == {
            "raises": [_fq("OrderDelivered"), _fq("OrderShipped")]
        }

    def test_value_object_beside_a_raise_is_not_recorded(self, ir):
        # ``annotate`` builds an OrderTag value object next to the raise; only
        # the registered event contributes to ``raises``.
        agg = ir["clusters"][_fq("Order")]["aggregate"]
        assert agg["method_edges"]["annotate"] == {"raises": [_fq("OrderCancelled")]}
        assert _fq("OrderTag") not in agg["method_edges"]["annotate"]["raises"]

    def test_construction_without_raise_records_no_edge(self, ir):
        # ``preview`` constructs an event but never calls ``raise_``.
        agg = ir["clusters"][_fq("Order")]["aggregate"]
        assert "preview" not in agg["method_edges"]

    def test_raise_without_construction_records_no_edge(self, ir):
        # ``escalate`` calls ``raise_`` but builds no event, so co-location
        # finds nothing to record.
        agg = ir["clusters"][_fq("Order")]["aggregate"]
        assert "escalate" not in agg["method_edges"]

    def test_entity_raises_are_recorded(self, ir):
        entity = ir["clusters"][_fq("Order")]["entities"][_fq("OrderLine")]
        assert entity["method_edges"] == {"adjust": {"raises": [_fq("LineAdjusted")]}}


class TestInvokes:
    """``invokes`` is derived by name-surface recognition against the scope."""

    def test_command_handler_invokes_unambiguous_method(self, ir):
        handler = ir["clusters"][_fq("Order")]["command_handlers"][
            _fq("OrderCommandHandler")
        ]
        assert handler["method_edges"]["handle_place"] == {
            "invokes": [{"element": _fq("Order"), "method": "place"}]
        }

    def test_invoke_edge_targets_an_entity_method(self, ir):
        # ``adjust`` is defined only on the OrderLine entity, so the resolved
        # edge names the entity half of the cluster surface (every other
        # positive invoke test resolves to the aggregate ``Order.place``).
        handler = ir["clusters"][_fq("Order")]["event_handlers"][_fq("OrderNotifier")]
        assert handler["method_edges"]["on_cancelled"] == {
            "invokes": [{"element": _fq("OrderLine"), "method": "adjust"}]
        }

    def test_ambiguous_name_records_no_invoke(self, ir):
        # ``handle_touch`` calls ``touch``, which both Order and OrderLine
        # define, so no edge is recorded and the method is absent.
        #
        # Pin the precondition, so this stays an ambiguity test and does not
        # silently degrade into a no-match test: ``touch`` genuinely resolves
        # to two cluster elements. Drop either ``touch`` and the call would
        # match one element and wrongly record an edge.
        assert "touch" in m.Order.__dict__
        assert "touch" in m.OrderLine.__dict__
        handler = ir["clusters"][_fq("Order")]["command_handlers"][
            _fq("OrderCommandHandler")
        ]
        assert "handle_touch" not in handler["method_edges"]

    def test_event_handler_invokes_through_its_cluster(self, ir):
        handler = ir["clusters"][_fq("Order")]["event_handlers"][_fq("OrderNotifier")]
        assert handler["method_edges"]["on_placed"] == {
            "invokes": [{"element": _fq("Order"), "method": "place"}]
        }

    def test_process_manager_invokes_through_handled_message_clusters(self, ir):
        pm = ir["flows"]["process_managers"][_fq("OrderProcess")]
        assert pm["method_edges"]["on_placed"] == {
            "invokes": [{"element": _fq("Order"), "method": "place"}]
        }

    def test_projector_invokes_through_handled_event_clusters(self, ir):
        projector = ir["projections"][_fq("OrderView")]["projectors"][
            _fq("OrderViewProjector")
        ]
        assert projector["method_edges"]["project_placed"] == {
            "invokes": [{"element": _fq("Order"), "method": "place"}]
        }

    def test_handler_whose_events_are_all_unowned_gets_no_edges(self):
        # A projector wired only to a stale event type no cluster owns has an
        # empty scope, so even a call that would otherwise match records nothing.
        domain = Domain(name="OrphanScope", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

            def place(self):
                self.raise_(OrderPlaced(order_id=self.id))

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier()

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class GhostProjector:
            @handle(OrderPlaced)
            def project(self, event):
                order = Order(name="x")
                order.place()

        domain.init(traverse=False)

        # Baseline: wired to OrderPlaced, whose cluster owns Order, ``project``
        # resolves the ``place`` call and records the edge. Without this the
        # absence below could not be told apart from a projector that never
        # records edges at all.
        ir = IRBuilder(domain).build()
        projector = ir["projections"][fqn(OrderView)]["projectors"][fqn(GhostProjector)]
        assert projector["method_edges"]["project"] == {
            "invokes": [{"element": fqn(Order), "method": "place"}]
        }

        # Rewire the projector to handle only a stale type (a renamed/removed
        # event), the one shape that reaches an empty invoke scope.
        method = next(iter(GhostProjector._handlers[OrderPlaced.__type__]))
        GhostProjector._handlers.clear()
        GhostProjector._handlers["OrphanScope.RemovedEvent.v1"] = {method}

        ir = IRBuilder(domain).build()

        projector = ir["projections"][fqn(OrderView)]["projectors"][fqn(GhostProjector)]
        assert "method_edges" not in projector


class TestSparsity:
    """A method with no edge is absent; an element with no edged method has no
    ``method_edges`` key at all."""

    def test_element_with_no_edged_method_has_no_key(self, ir):
        catalog = ir["clusters"][_fq("Catalog")]["aggregate"]
        assert "method_edges" not in catalog

    def test_only_edged_methods_appear(self, ir):
        agg = ir["clusters"][_fq("Order")]["aggregate"]
        # ``touch`` neither raises nor is a handler method, so it is absent.
        assert "touch" not in agg["method_edges"]
        assert set(agg["method_edges"]) == {
            "annotate",
            "place",
            "register_new",
            "split",
        }


class TestFailOpen:
    """An element whose source cannot be read yields no edges, build succeeds."""

    def test_unreadable_source_yields_no_edges(self):
        # A dynamically-built aggregate has no source file, so the view returns
        # empty facts for it. Its method constructs and raises a *registered*
        # event — the exact shape that earns the on-disk ``Order.place`` an
        # edge — so an unreadable source is the only remaining reason no edge
        # is recorded. The on-disk ``Order`` is registered alongside as a
        # positive control: with the derivation active its ``place`` edge is
        # present, so the Ghost's empty result cannot be blamed on a dead pass.
        def _raise_method(self):
            self.raise_(m.OrderPlaced(order_id=self.id))

        Ghost = type(
            "GhostOrder",
            (BaseAggregate,),
            {"name": String(max_length=20), "do_raise": _raise_method},
        )
        domain = Domain(name="GhostEdges", root_path=".")
        domain.register(m.Order)
        domain.register(m.OrderPlaced, part_of=m.Order)
        domain.register(Ghost)
        domain.init(traverse=False)

        ir = IRBuilder(domain).build()

        # Positive control: the on-disk twin's raise IS materialized.
        on_disk = ir["clusters"][_fq("Order")]["aggregate"]
        assert on_disk["method_edges"]["place"] == {"raises": [_fq("OrderPlaced")]}
        # Fail-open: the source-less Ghost, written the same way, records nothing.
        cluster = ir["clusters"][fqn(Ghost)]
        assert "method_edges" not in cluster["aggregate"]


class TestSchemaConformance:
    """The materialized ``method_edges`` validates against the v0.2.0 schema."""

    def test_built_ir_validates(self, ir):
        jsonschema.validate(ir, load_schema())

    def test_empty_method_edges_is_rejected(self, ir):
        """Sparsity is a schema rule, not just a builder habit.

        The builder only ever writes a non-empty map, so an element carrying
        ``method_edges: {}`` came from somewhere else and should not validate.
        """
        ir["clusters"][_fq("Catalog")]["aggregate"]["method_edges"] = {}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(ir, load_schema())
