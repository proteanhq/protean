"""IR extraction of the ``sequential_by`` option (#830, ADR-0028).

The field is sparse: it appears on a handler's IR dict only when set, and
carries the declared value (a field name for event/command handlers, the
boolean opt-in for process managers; a field name for projectors too).
"""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.ir import SCHEMA_PATH
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


class OrderSummary(BaseProjection):
    order_id: Identifier(identifier=True)


class PartitionedOrderProjector(BaseProjector):
    @on(OrderPlaced)
    def on_placed(self, event):
        pass


class PlainOrderProjector(BaseProjector):
    @on(OrderPlaced)
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
    domain.register(OrderSummary)
    domain.register(
        PartitionedOrderProjector,
        projector_for=OrderSummary,
        aggregates=[Order],
        sequential_by="order_id",
    )
    domain.register(PlainOrderProjector, projector_for=OrderSummary, aggregates=[Order])
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

    def _projectors(self, ir):
        projectors = {}
        for projection in ir["projections"].values():
            for entry in projection["projectors"].values():
                projectors[entry["name"]] = entry
        assert projectors, "no projectors found in the IR"
        return projectors

    def test_projector_carries_sequential_by(self):
        projectors = self._projectors(_build_ir())
        assert projectors["PartitionedOrderProjector"]["sequential_by"] == "order_id"

    def test_projector_omits_when_unset(self):
        projectors = self._projectors(_build_ir())
        assert "sequential_by" not in projectors["PlainOrderProjector"]

    def test_ir_validates_against_schema(self):
        jsonschema.validate(_build_ir(), json.loads(SCHEMA_PATH.read_text()))


_SEQUENTIAL_KINDS = ("event_handler", "command_handler", "projector", "process_manager")


def _schema():
    return json.loads(SCHEMA_PATH.read_text())


def _strict_schema():
    """Close the four handler definitions to keys the schema does not declare.

    ``additionalProperties`` sees only sibling ``properties``, so the
    ``base_element`` keys are merged into the object branch before closing it.
    """
    schema = copy.deepcopy(_schema())
    base_properties = schema["$defs"]["base_element"]["properties"]
    for kind in _SEQUENTIAL_KINDS:
        branch = schema["$defs"][kind]["allOf"][1]
        branch["properties"] = {**base_properties, **branch["properties"]}
        branch["additionalProperties"] = False
    return schema


def _all_with_sequential_by(ir):
    cluster = _order_cluster(ir)
    projectors = [
        entry
        for projection in ir["projections"].values()
        for entry in projection["projectors"].values()
    ]
    return [
        *cluster["event_handlers"].values(),
        *cluster["command_handlers"].values(),
        *projectors,
        *ir["flows"]["process_managers"].values(),
    ]


def _element(ir, name):
    for element in _all_with_sequential_by(ir):
        if element["name"] == name:
            return element
    pytest.fail(f"{name} not found in the IR")


def _error_paths(ir):
    validator = jsonschema.Draft202012Validator(_schema())
    return [list(error.absolute_path) for error in validator.iter_errors(ir)]


def _path_to(ir, name):
    """Return the JSON path to ``name``'s ``sequential_by`` key."""
    cluster_fqn, cluster = next(
        (fqn, c)
        for fqn, c in ir["clusters"].items()
        if c["aggregate"]["name"] == "Order"
    )
    for section in ("event_handlers", "command_handlers"):
        for fqn, element in cluster[section].items():
            if element["name"] == name:
                return ["clusters", cluster_fqn, section, fqn, "sequential_by"]
    for projection_fqn, projection in ir["projections"].items():
        for fqn, element in projection["projectors"].items():
            if element["name"] == name:
                return [
                    "projections",
                    projection_fqn,
                    "projectors",
                    fqn,
                    "sequential_by",
                ]
    for fqn, element in ir["flows"]["process_managers"].items():
        if element["name"] == name:
            return ["flows", "process_managers", fqn, "sequential_by"]
    pytest.fail(f"{name} not found in the IR")


@pytest.mark.no_test_domain
class TestSequentialBySchema:
    def test_ir_validates_when_handler_definitions_are_closed(self):
        ir = _build_ir()
        carrying = {
            element["element_type"]
            for element in _all_with_sequential_by(ir)
            if "sequential_by" in element
        }
        assert carrying == {
            "EVENT_HANDLER",
            "COMMAND_HANDLER",
            "PROJECTOR",
            "PROCESS_MANAGER",
        }

        validator = jsonschema.Draft202012Validator(_strict_schema())
        errors = [error.message for error in validator.iter_errors(ir)]
        assert errors == []

    @pytest.mark.parametrize("value", ["", True, 5])
    @pytest.mark.parametrize(
        "name",
        ["PartitionedOrderHandler", "OrderCommandHandler", "PartitionedOrderProjector"],
    )
    def test_partition_key_that_is_not_a_field_name_is_rejected(self, name, value):
        ir = _build_ir()
        _element(ir, name)["sequential_by"] = value
        assert _error_paths(ir) == [_path_to(ir, name)]

    def test_string_on_process_manager_is_rejected(self):
        ir = _build_ir()
        _element(ir, "OrderPM")["sequential_by"] = "x"
        assert _error_paths(ir) == [_path_to(ir, "OrderPM")]

    def test_false_on_process_manager_validates(self):
        ir = _build_ir()
        _element(ir, "OrderPM")["sequential_by"] = False
        assert _error_paths(ir) == []


_SPEC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "concepts"
    / "internals"
    / "ir-specification.md"
)


def _spec_section(start, end):
    text = _SPEC_PATH.read_text()
    begin = text.index(start)
    return text[begin : text.index(end, begin)]


@pytest.mark.no_test_domain
class TestSequentialBySpecification:
    @pytest.mark.parametrize(
        "start, end",
        [
            ("### Command Handler", "### Event Handler"),
            ("### Event Handler", "### Other Cluster Elements"),
            ("**Projectors** specify", "**Queries**"),
            ("### Process Managers", "### Subscribers"),
        ],
    )
    def test_each_kind_documents_the_key(self, start, end):
        assert "`sequential_by`" in _spec_section(start, end)
