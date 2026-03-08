"""Integration tests for IR builder — exercises all sections simultaneously."""

import pytest
from jsonschema import validate, ValidationError

from protean.ir import load_schema
from protean.ir.builder import IRBuilder

from .elements import build_integration_domain


@pytest.fixture(scope="module")
def domain():
    return build_integration_domain()


@pytest.fixture(scope="module")
def ir(domain):
    return IRBuilder(domain).build()


@pytest.fixture(scope="module")
def schema():
    return load_schema()


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestSchemaValidation:
    def test_ir_validates_against_schema(self, ir, schema):
        try:
            validate(instance=ir, schema=schema)
        except ValidationError as exc:
            pytest.fail(
                f"Integration IR failed schema validation:\n"
                f"  Path: {'.'.join(str(p) for p in exc.absolute_path)}\n"
                f"  Message: {exc.message}"
            )


# ---------------------------------------------------------------------------
# Top-level structure
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestTopLevelStructure:
    def test_required_keys_present(self, ir):
        required = [
            "$schema",
            "ir_version",
            "generated_at",
            "checksum",
            "domain",
            "clusters",
            "projections",
            "flows",
            "elements",
            "diagnostics",
        ]
        for key in required:
            assert key in ir, f"Missing top-level key: {key}"

    def test_domain_name(self, ir):
        assert ir["domain"]["name"] == "Fulfillment"

    def test_checksum_format(self, ir):
        assert ir["checksum"].startswith("sha256:")
        assert len(ir["checksum"]) == 71


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestClusters:
    def test_cluster_count(self, ir):
        # 3 domain aggregates + MemoryMessage (internal event store aggregate)
        assert len(ir["clusters"]) == 4

    def test_cluster_names(self, ir):
        names = {c["aggregate"]["name"] for c in ir["clusters"].values()}
        assert names == {"Order", "Inventory", "Shipment", "MemoryMessage"}

    def test_order_cluster_has_entity(self, ir):
        order = self._cluster_by_name(ir, "Order")
        assert len(order["entities"]) == 1
        entity = next(iter(order["entities"].values()))
        assert entity["name"] == "LineItem"

    def test_order_cluster_has_commands(self, ir):
        order = self._cluster_by_name(ir, "Order")
        assert len(order["commands"]) == 1
        cmd = next(iter(order["commands"].values()))
        assert cmd["name"] == "PlaceOrder"

    def test_order_cluster_has_events(self, ir):
        order = self._cluster_by_name(ir, "Order")
        assert len(order["events"]) == 2
        event_names = {e["name"] for e in order["events"].values()}
        assert "OrderPlaced" in event_names
        assert "OrderShipped" in event_names

    def test_order_cluster_has_command_handler(self, ir):
        order = self._cluster_by_name(ir, "Order")
        assert len(order["command_handlers"]) == 1

    def test_inventory_cluster_has_event_handler(self, ir):
        inv = self._cluster_by_name(ir, "Inventory")
        assert len(inv["event_handlers"]) == 1
        handler = next(iter(inv["event_handlers"].values()))
        assert handler["name"] == "InventoryReactor"

    def test_cross_aggregate_handler_wiring(self, ir):
        """InventoryReactor handles OrderPlaced from another aggregate."""
        inv = self._cluster_by_name(ir, "Inventory")
        handler = next(iter(inv["event_handlers"].values()))
        # handler map keys are __type__ strings for handled events
        handled_types = list(handler["handlers"].keys())
        assert len(handled_types) == 1
        assert "OrderPlaced" in handled_types[0]

    def test_shipment_cluster_has_command_and_event(self, ir):
        ship = self._cluster_by_name(ir, "Shipment")
        assert len(ship["commands"]) == 1
        assert len(ship["events"]) == 1

    def test_shared_value_object_in_order_cluster(self, ir):
        order = self._cluster_by_name(ir, "Order")
        vo_names = {vo["name"] for vo in order["value_objects"].values()}
        assert "Money" in vo_names

    @staticmethod
    def _cluster_by_name(ir: dict, name: str) -> dict:
        for cluster in ir["clusters"].values():
            if cluster["aggregate"]["name"] == name:
                return cluster
        pytest.fail(f"Cluster '{name}' not found")


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestProjections:
    def test_projection_count(self, ir):
        assert len(ir["projections"]) == 1

    def test_projection_structure(self, ir):
        proj_entry = next(iter(ir["projections"].values()))
        assert proj_entry["projection"]["name"] == "OrderDashboard"
        assert len(proj_entry["projectors"]) == 1
        assert len(proj_entry["queries"]) == 1
        assert len(proj_entry["query_handlers"]) == 1

    def test_projector_handles_two_events(self, ir):
        proj_entry = next(iter(ir["projections"].values()))
        projector = next(iter(proj_entry["projectors"].values()))
        assert len(projector["handlers"]) == 2


# ---------------------------------------------------------------------------
# Flows
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestFlows:
    def test_process_manager_present(self, ir):
        pms = ir["flows"]["process_managers"]
        assert len(pms) == 1
        pm = next(iter(pms.values()))
        assert pm["name"] == "OrderFulfillment"

    def test_process_manager_stream_categories(self, ir):
        pm = next(iter(ir["flows"]["process_managers"].values()))
        categories = pm["stream_categories"]
        # Stream categories are prefixed with domain name
        assert any("order" in c for c in categories)
        assert any("shipment" in c for c in categories)

    def test_process_manager_handlers(self, ir):
        pm = next(iter(ir["flows"]["process_managers"].values()))
        handlers = pm["handlers"]
        assert len(handlers) == 2

        # Find start handler and end handler
        start_found = False
        end_found = False
        for handler_meta in handlers.values():
            if handler_meta.get("start"):
                start_found = True
            if handler_meta.get("end"):
                end_found = True
        assert start_found, "No start handler found"
        assert end_found, "No end handler found"

    def test_subscriber_present(self, ir):
        subs = ir["flows"]["subscribers"]
        assert len(subs) == 1
        sub = next(iter(subs.values()))
        assert sub["name"] == "ExternalPaymentSubscriber"
        assert sub["broker"] == "default"
        assert sub["stream"] == "payment_gateway"

    def test_domain_services_empty(self, ir):
        assert ir["flows"]["domain_services"] == {}


# ---------------------------------------------------------------------------
# Elements index
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestElementsIndex:
    EXPECTED_TYPES = [
        "AGGREGATE",
        "APPLICATION_SERVICE",
        "COMMAND",
        "COMMAND_HANDLER",
        "DATABASE_MODEL",
        "DOMAIN_SERVICE",
        "ENTITY",
        "EVENT",
        "EVENT_HANDLER",
        "PROCESS_MANAGER",
        "PROJECTION",
        "PROJECTOR",
        "QUERY",
        "QUERY_HANDLER",
        "REPOSITORY",
        "SUBSCRIBER",
        "VALUE_OBJECT",
    ]

    def test_all_element_types_present(self, ir):
        for etype in self.EXPECTED_TYPES:
            assert etype in ir["elements"], f"Missing element type: {etype}"

    def test_aggregate_count(self, ir):
        # 3 domain aggregates + MemoryMessage (internal)
        assert len(ir["elements"]["AGGREGATE"]) == 4

    def test_command_count(self, ir):
        assert len(ir["elements"]["COMMAND"]) == 2

    def test_event_count(self, ir):
        # OrderPlaced, OrderShipped, StockReserved, ShipmentDispatched
        # + _OrderFulfillmentTransition (auto-generated by process manager)
        assert len(ir["elements"]["EVENT"]) == 5

    def test_projection_in_index(self, ir):
        assert len(ir["elements"]["PROJECTION"]) == 1

    def test_projector_in_index(self, ir):
        assert len(ir["elements"]["PROJECTOR"]) == 1

    def test_subscriber_in_index(self, ir):
        assert len(ir["elements"]["SUBSCRIBER"]) == 1

    def test_process_manager_in_index(self, ir):
        assert len(ir["elements"]["PROCESS_MANAGER"]) == 1

    def test_query_in_index(self, ir):
        assert len(ir["elements"]["QUERY"]) == 1

    def test_query_handler_in_index(self, ir):
        assert len(ir["elements"]["QUERY_HANDLER"]) == 1

    def test_value_object_in_index(self, ir):
        assert len(ir["elements"]["VALUE_OBJECT"]) == 1

    def test_lists_are_sorted(self, ir):
        for etype, fqns in ir["elements"].items():
            assert fqns == sorted(fqns), f"Elements[{etype}] not sorted"


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiagnostics:
    def test_diagnostics_is_list(self, ir):
        assert isinstance(ir["diagnostics"], list)

    def test_unhandled_events_detected(self, ir):
        """StockReserved has no handler — should produce a diagnostic."""
        unhandled = [d for d in ir["diagnostics"] if d["code"] == "UNHANDLED_EVENT"]
        unhandled_elements = {d["element"] for d in unhandled}
        # StockReserved is defined but never handled
        assert any("StockReserved" in el for el in unhandled_elements)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDeterminism:
    def test_identical_checksums(self):
        """domain.to_ir() called twice must produce identical checksums."""
        domain = build_integration_domain()
        ir1 = domain.to_ir()
        ir2 = domain.to_ir()
        assert ir1["checksum"] == ir2["checksum"]

    def test_identical_structure(self):
        """Two IR builds from the same domain must be structurally identical
        (ignoring generated_at timestamp)."""
        domain = build_integration_domain()
        ir1 = domain.to_ir()
        ir2 = domain.to_ir()

        # Remove non-deterministic field
        ir1.pop("generated_at")
        ir2.pop("generated_at")
        assert ir1 == ir2
