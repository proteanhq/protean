"""Tests for IRBuilder cluster assembly — aggregates, entities, value objects."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_cluster_test_domain


@pytest.fixture
def cluster_ir():
    """Return the full IR for the cluster test domain."""
    domain = build_cluster_test_domain()
    return IRBuilder(domain).build()


@pytest.fixture
def order_cluster(cluster_ir):
    """Return the Order aggregate's cluster from the IR."""
    # Find the cluster keyed by the Order aggregate FQN
    for key, cluster in cluster_ir["clusters"].items():
        if cluster["aggregate"]["name"] == "Order":
            return cluster
    pytest.fail("Order cluster not found")


@pytest.mark.no_test_domain
class TestClusterStructure:
    """Verify cluster dict has all required subsections."""

    def test_clusters_present(self, cluster_ir):
        # At least the Order cluster; adapter-internal aggregates may also appear
        assert "tests.ir.elements.Order" in cluster_ir["clusters"]

    def test_cluster_has_all_subsections(self, order_cluster):
        expected = [
            "aggregate",
            "application_services",
            "command_handlers",
            "commands",
            "database_models",
            "entities",
            "event_handlers",
            "events",
            "repositories",
            "value_objects",
        ]
        for key in expected:
            assert key in order_cluster, f"Missing cluster subsection: {key}"

    def test_empty_subsections_are_empty_dicts(self, order_cluster):
        for key in [
            "application_services",
            "command_handlers",
            "commands",
            "database_models",
            "event_handlers",
            "events",
            "repositories",
        ]:
            assert order_cluster[key] == {}


@pytest.mark.no_test_domain
class TestAggregateExtraction:
    """Verify aggregate IR dict structure."""

    def test_element_type(self, order_cluster):
        assert order_cluster["aggregate"]["element_type"] == "AGGREGATE"

    def test_name(self, order_cluster):
        assert order_cluster["aggregate"]["name"] == "Order"

    def test_fqn_present(self, order_cluster):
        fqn_val = order_cluster["aggregate"]["fqn"]
        assert fqn_val.endswith(".Order")

    def test_module(self, order_cluster):
        assert order_cluster["aggregate"]["module"] is not None

    def test_identity_field(self, order_cluster):
        assert order_cluster["aggregate"]["identity_field"] == "id"

    def test_description_from_docstring(self, order_cluster):
        assert order_cluster["aggregate"]["description"] == (
            "An order aggregate with invariants."
        )

    def test_fields_present(self, order_cluster):
        fields = order_cluster["aggregate"]["fields"]
        assert "customer_name" in fields
        assert "total" in fields
        assert "shipping_address" in fields
        assert "items" in fields
        assert "id" in fields

    def test_invariants(self, order_cluster):
        inv = order_cluster["aggregate"]["invariants"]
        assert "total_must_be_positive" in inv["post"]
        assert inv["pre"] == []

    def test_options_present(self, order_cluster):
        opts = order_cluster["aggregate"]["options"]
        assert "auto_add_id_field" in opts
        assert "fact_events" in opts
        assert "is_event_sourced" in opts
        assert "limit" in opts
        assert "provider" in opts
        assert "schema_name" in opts
        assert "stream_category" in opts

    def test_options_default_values(self, order_cluster):
        opts = order_cluster["aggregate"]["options"]
        assert opts["auto_add_id_field"] is True
        assert opts["is_event_sourced"] is False
        assert opts["fact_events"] is False
        assert opts["provider"] == "default"

    def test_no_apply_handlers_for_non_es(self, order_cluster):
        assert "apply_handlers" not in order_cluster["aggregate"]

    def test_keys_sorted(self, order_cluster):
        keys = list(order_cluster["aggregate"].keys())
        assert keys == sorted(keys)

    def test_options_keys_sorted(self, order_cluster):
        keys = list(order_cluster["aggregate"]["options"].keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestEntityExtraction:
    """Verify entity appears in the correct cluster."""

    def test_entity_in_cluster(self, order_cluster):
        assert len(order_cluster["entities"]) == 1

    def test_entity_element_type(self, order_cluster):
        entity = next(iter(order_cluster["entities"].values()))
        assert entity["element_type"] == "ENTITY"

    def test_entity_name(self, order_cluster):
        entity = next(iter(order_cluster["entities"].values()))
        assert entity["name"] == "LineItem"

    def test_entity_part_of(self, order_cluster):
        entity = next(iter(order_cluster["entities"].values()))
        agg_fqn = order_cluster["aggregate"]["fqn"]
        assert entity["part_of"] == agg_fqn

    def test_entity_identity_field(self, order_cluster):
        entity = next(iter(order_cluster["entities"].values()))
        assert entity["identity_field"] == "id"

    def test_entity_fields(self, order_cluster):
        entity = next(iter(order_cluster["entities"].values()))
        assert "product_name" in entity["fields"]
        assert "quantity" in entity["fields"]
        assert "unit_price" in entity["fields"]

    def test_entity_options(self, order_cluster):
        entity = next(iter(order_cluster["entities"].values()))
        opts = entity["options"]
        assert "auto_add_id_field" in opts
        assert "limit" in opts
        assert "provider" in opts
        assert "schema_name" in opts
        # Entity should NOT have aggregate-specific options
        assert "fact_events" not in opts
        assert "is_event_sourced" not in opts
        assert "stream_category" not in opts

    def test_entity_keys_sorted(self, order_cluster):
        entity = next(iter(order_cluster["entities"].values()))
        keys = list(entity.keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestValueObjectExtraction:
    """Verify value object appears in the correct cluster."""

    def test_vo_in_cluster(self, order_cluster):
        assert len(order_cluster["value_objects"]) == 1

    def test_vo_element_type(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        assert vo["element_type"] == "VALUE_OBJECT"

    def test_vo_name(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        assert vo["name"] == "ShippingAddress"

    def test_vo_part_of(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        agg_fqn = order_cluster["aggregate"]["fqn"]
        assert vo["part_of"] == agg_fqn

    def test_vo_description(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        assert vo["description"] == "A shipping address value object."

    def test_vo_fields(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        assert "street" in vo["fields"]
        assert "city" in vo["fields"]

    def test_vo_no_identity_field(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        assert "identity_field" not in vo

    def test_vo_no_options(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        assert "options" not in vo

    def test_vo_keys_sorted(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        keys = list(vo.keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestClusterKeySorting:
    """Verify cluster-level dict keys are sorted."""

    def test_cluster_keys_sorted(self, cluster_ir):
        keys = list(cluster_ir["clusters"].keys())
        assert keys == sorted(keys)

    def test_entity_keys_sorted_within_cluster(self, order_cluster):
        keys = list(order_cluster["entities"].keys())
        assert keys == sorted(keys)

    def test_vo_keys_sorted_within_cluster(self, order_cluster):
        keys = list(order_cluster["value_objects"].keys())
        assert keys == sorted(keys)
