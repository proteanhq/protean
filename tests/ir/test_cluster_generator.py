"""Tests for the aggregate cluster diagram generator.

Covers: generate_cluster_diagram, single-cluster filtering,
aggregate stereotypes, entity/VO rendering, cross-aggregate references,
invariant notes, and edge cases.
"""

import pytest

from protean.ir.generators.clusters import generate_cluster_diagram


# ------------------------------------------------------------------
# Fixtures — minimal IR dicts for focused tests
# ------------------------------------------------------------------


def _minimal_aggregate(
    fqn: str = "app.Order",
    *,
    fields: dict | None = None,
    options: dict | None = None,
    invariants: dict | None = None,
) -> dict:
    """Build a minimal cluster with just an aggregate."""
    return {
        fqn: {
            "aggregate": {
                "fqn": fqn,
                "name": fqn.rsplit(".", 1)[-1],
                "fields": fields
                or {
                    "id": {
                        "kind": "auto",
                        "type": "Auto",
                        "identifier": True,
                        "unique": True,
                        "auto_generated": True,
                    },
                },
                "identity_field": "id",
                "invariants": invariants or {"pre": [], "post": []},
                "options": options
                or {
                    "is_event_sourced": False,
                    "fact_events": False,
                },
            },
            "entities": {},
            "value_objects": {},
            "commands": {},
            "events": {},
            "command_handlers": {},
            "event_handlers": {},
            "repositories": {},
            "application_services": {},
            "database_models": {},
        }
    }


def _ir_with_clusters(clusters: dict) -> dict:
    return {"clusters": clusters}


# ------------------------------------------------------------------
# Empty / missing clusters
# ------------------------------------------------------------------


class TestEmptyIR:
    def test_empty_clusters(self):
        result = generate_cluster_diagram({"clusters": {}})
        assert result == "classDiagram"

    def test_missing_clusters_key(self):
        result = generate_cluster_diagram({})
        assert result == "classDiagram"

    def test_unknown_cluster_fqn(self):
        ir = _ir_with_clusters(_minimal_aggregate())
        result = generate_cluster_diagram(ir, cluster_fqn="app.DoesNotExist")
        assert result == "classDiagram"


# ------------------------------------------------------------------
# Single aggregate rendering
# ------------------------------------------------------------------


class TestSingleAggregate:
    def test_aggregate_class_rendered(self):
        ir = _ir_with_clusters(_minimal_aggregate())
        result = generate_cluster_diagram(ir)
        assert "classDiagram" in result
        assert 'class app_Order["Order"]' in result
        assert "<<Aggregate>>" in result

    def test_aggregate_fields_rendered(self):
        fields = {
            "id": {
                "kind": "auto",
                "type": "Auto",
                "identifier": True,
                "unique": True,
                "auto_generated": True,
            },
            "name": {
                "kind": "standard",
                "type": "String",
                "required": True,
            },
        }
        ir = _ir_with_clusters(_minimal_aggregate(fields=fields))
        result = generate_cluster_diagram(ir)
        # Constraints use Mermaid generic notation ~tag~ (no parentheses)
        assert "+id Auto~identifier~" in result
        assert "+name String~required~" in result

    def test_event_sourced_stereotype(self):
        ir = _ir_with_clusters(
            _minimal_aggregate(options={"is_event_sourced": True, "fact_events": False})
        )
        result = generate_cluster_diagram(ir)
        assert "<<Aggregate, EventSourced>>" in result

    def test_fact_events_stereotype(self):
        ir = _ir_with_clusters(
            _minimal_aggregate(options={"is_event_sourced": False, "fact_events": True})
        )
        result = generate_cluster_diagram(ir)
        assert "<<Aggregate, FactEvents>>" in result

    def test_event_sourced_and_fact_events(self):
        ir = _ir_with_clusters(
            _minimal_aggregate(options={"is_event_sourced": True, "fact_events": True})
        )
        result = generate_cluster_diagram(ir)
        assert "<<Aggregate, EventSourced, FactEvents>>" in result


# ------------------------------------------------------------------
# Invariant notes
# ------------------------------------------------------------------


class TestInvariantNotes:
    def test_post_invariant_rendered(self):
        ir = _ir_with_clusters(
            _minimal_aggregate(
                invariants={"pre": [], "post": ["must_have_positive_total"]}
            )
        )
        result = generate_cluster_diagram(ir)
        assert "note for app_Order" in result
        assert "must_have_positive_total" in result

    def test_pre_invariant_rendered(self):
        ir = _ir_with_clusters(
            _minimal_aggregate(invariants={"pre": ["check_balance"], "post": []})
        )
        result = generate_cluster_diagram(ir)
        assert "check_balance" in result

    def test_no_invariants_no_note(self):
        ir = _ir_with_clusters(_minimal_aggregate(invariants={"pre": [], "post": []}))
        result = generate_cluster_diagram(ir)
        assert "note for" not in result

    def test_multiple_invariants_combined(self):
        ir = _ir_with_clusters(
            _minimal_aggregate(
                invariants={"pre": ["pre_check"], "post": ["post_check"]}
            )
        )
        result = generate_cluster_diagram(ir)
        assert 'note for app_Order "pre_check"' in result
        assert 'note for app_Order "post_check"' in result


# ------------------------------------------------------------------
# Entities with has_many relationships
# ------------------------------------------------------------------


class TestEntities:
    @pytest.fixture()
    def ir_with_entity(self):
        clusters = _minimal_aggregate(
            fields={
                "id": {"kind": "auto", "type": "Auto", "identifier": True},
                "items": {"kind": "has_many", "target": "app.OrderItem"},
            },
        )
        clusters["app.Order"]["entities"] = {
            "app.OrderItem": {
                "fqn": "app.OrderItem",
                "name": "OrderItem",
                "fields": {
                    "id": {"kind": "auto", "type": "Auto", "identifier": True},
                    "quantity": {
                        "kind": "standard",
                        "type": "Integer",
                        "required": True,
                    },
                },
                "identity_field": "id",
                "invariants": {"pre": [], "post": []},
                "part_of": "app.Order",
            }
        }
        return _ir_with_clusters(clusters)

    def test_entity_class_rendered(self, ir_with_entity):
        result = generate_cluster_diagram(ir_with_entity)
        assert 'class app_OrderItem["OrderItem"]' in result
        assert "<<Entity>>" in result

    def test_entity_fields_rendered(self, ir_with_entity):
        result = generate_cluster_diagram(ir_with_entity)
        assert "+quantity Integer~required~" in result

    def test_has_many_relationship(self, ir_with_entity):
        result = generate_cluster_diagram(ir_with_entity)
        assert 'app_Order "1" o-- "*" app_OrderItem : OrderItem' in result


# ------------------------------------------------------------------
# Value Objects with composition
# ------------------------------------------------------------------


class TestValueObjects:
    @pytest.fixture()
    def ir_with_vo(self):
        clusters = _minimal_aggregate(
            fields={
                "id": {"kind": "auto", "type": "Auto", "identifier": True},
                "address": {"kind": "value_object", "target": "app.Address"},
            },
        )
        clusters["app.Order"]["value_objects"] = {
            "app.Address": {
                "fqn": "app.Address",
                "name": "Address",
                "fields": {
                    "street": {"kind": "standard", "type": "String", "required": True},
                    "city": {"kind": "standard", "type": "String", "required": True},
                },
                "invariants": {"pre": [], "post": []},
                "part_of": "app.Order",
            }
        }
        return _ir_with_clusters(clusters)

    def test_vo_class_rendered(self, ir_with_vo):
        result = generate_cluster_diagram(ir_with_vo)
        assert 'class app_Address["Address"]' in result
        assert "<<ValueObject>>" in result

    def test_vo_fields_rendered(self, ir_with_vo):
        result = generate_cluster_diagram(ir_with_vo)
        assert "+street String~required~" in result
        assert "+city String~required~" in result

    def test_composition_arrow(self, ir_with_vo):
        result = generate_cluster_diagram(ir_with_vo)
        assert "app_Order *-- app_Address : Address" in result

    def test_value_object_list_composition(self):
        clusters = _minimal_aggregate(
            fields={
                "id": {"kind": "auto", "type": "Auto", "identifier": True},
                "tags": {"kind": "value_object_list", "target": "app.Tag"},
            },
        )
        clusters["app.Order"]["value_objects"] = {
            "app.Tag": {
                "fqn": "app.Tag",
                "name": "Tag",
                "fields": {
                    "label": {"kind": "standard", "type": "String"},
                },
                "invariants": {"pre": [], "post": []},
            }
        }
        ir = _ir_with_clusters(clusters)
        result = generate_cluster_diagram(ir)
        assert "app_Order *-- app_Tag : Tag" in result


# ------------------------------------------------------------------
# Cross-aggregate references
# ------------------------------------------------------------------


class TestCrossAggregateReferences:
    @pytest.fixture()
    def ir_with_cross_ref(self):
        order_clusters = _minimal_aggregate(
            fqn="app.Order",
            fields={
                "id": {"kind": "auto", "type": "Auto", "identifier": True},
                "items": {"kind": "has_many", "target": "app.OrderItem"},
            },
        )
        order_clusters["app.Order"]["entities"] = {
            "app.OrderItem": {
                "fqn": "app.OrderItem",
                "name": "OrderItem",
                "fields": {
                    "id": {"kind": "auto", "type": "Auto", "identifier": True},
                    "product_id": {
                        "kind": "reference",
                        "target": "app.Product",
                        "linked_attribute": "id",
                    },
                },
                "identity_field": "id",
                "invariants": {"pre": [], "post": []},
            }
        }

        product_clusters = _minimal_aggregate(fqn="app.Product")

        all_clusters = {}
        all_clusters.update(order_clusters)
        all_clusters.update(product_clusters)
        return _ir_with_clusters(all_clusters)

    def test_cross_ref_arrow_rendered(self, ir_with_cross_ref):
        result = generate_cluster_diagram(ir_with_cross_ref)
        assert "app_OrderItem ..> app_Product : product_id" in result

    def test_single_cluster_no_cross_refs(self, ir_with_cross_ref):
        """When filtering to a single cluster, cross-refs are not shown."""
        result = generate_cluster_diagram(ir_with_cross_ref, cluster_fqn="app.Order")
        assert "..>" not in result

    def test_aggregate_level_cross_ref(self):
        """Reference field on aggregate itself (not entity) is rendered."""
        order_clusters = _minimal_aggregate(
            fqn="app.Order",
            fields={
                "id": {"kind": "auto", "type": "Auto", "identifier": True},
                "customer_id": {
                    "kind": "reference",
                    "target": "app.Customer",
                    "linked_attribute": "id",
                },
            },
        )
        customer_clusters = _minimal_aggregate(fqn="app.Customer")
        all_clusters = {}
        all_clusters.update(order_clusters)
        all_clusters.update(customer_clusters)
        ir = _ir_with_clusters(all_clusters)
        result = generate_cluster_diagram(ir)
        assert "app_Order ..> app_Customer : customer_id" in result

    def test_self_referencing_entity_excluded(self):
        """Reference fields pointing back to own aggregate are not cross-refs."""
        clusters = _minimal_aggregate(
            fqn="app.Order",
            fields={
                "id": {"kind": "auto", "type": "Auto", "identifier": True},
                "items": {"kind": "has_many", "target": "app.OrderItem"},
            },
        )
        clusters["app.Order"]["entities"] = {
            "app.OrderItem": {
                "fqn": "app.OrderItem",
                "name": "OrderItem",
                "fields": {
                    "id": {"kind": "auto", "type": "Auto", "identifier": True},
                    "order_id": {
                        "kind": "reference",
                        "target": "app.Order",
                        "linked_attribute": "id",
                        "auto_generated": True,
                    },
                },
                "identity_field": "id",
                "invariants": {"pre": [], "post": []},
            }
        }
        ir = _ir_with_clusters(clusters)
        result = generate_cluster_diagram(ir)
        assert "..>" not in result


# ------------------------------------------------------------------
# Single-cluster filtering
# ------------------------------------------------------------------


class TestSingleClusterFilter:
    def test_single_cluster_only(self):
        order_clusters = _minimal_aggregate(fqn="app.Order")
        product_clusters = _minimal_aggregate(fqn="app.Product")
        all_clusters = {}
        all_clusters.update(order_clusters)
        all_clusters.update(product_clusters)
        ir = _ir_with_clusters(all_clusters)

        result = generate_cluster_diagram(ir, cluster_fqn="app.Order")
        assert "app_Order" in result
        assert "app_Product" not in result


# ------------------------------------------------------------------
# Multiple clusters rendered together
# ------------------------------------------------------------------


class TestMultipleClusters:
    def test_both_clusters_rendered(self):
        order_clusters = _minimal_aggregate(fqn="app.Order")
        product_clusters = _minimal_aggregate(fqn="app.Product")
        all_clusters = {}
        all_clusters.update(order_clusters)
        all_clusters.update(product_clusters)
        ir = _ir_with_clusters(all_clusters)

        result = generate_cluster_diagram(ir)
        assert "app_Order" in result
        assert "app_Product" in result


# ------------------------------------------------------------------
# Field constraint rendering
# ------------------------------------------------------------------


class TestFieldConstraints:
    def test_identifier_field(self):
        fields = {
            "id": {
                "kind": "auto",
                "type": "Auto",
                "identifier": True,
                "unique": True,
                "auto_generated": True,
            },
        }
        ir = _ir_with_clusters(_minimal_aggregate(fields=fields))
        result = generate_cluster_diagram(ir)
        assert "+id Auto~identifier~" in result

    def test_required_field(self):
        fields = {
            "id": {"kind": "auto", "type": "Auto", "identifier": True},
            "name": {"kind": "standard", "type": "String", "required": True},
        }
        ir = _ir_with_clusters(_minimal_aggregate(fields=fields))
        result = generate_cluster_diagram(ir)
        assert "+name String~required~" in result

    def test_unconstrained_field(self):
        fields = {
            "id": {"kind": "auto", "type": "Auto", "identifier": True},
            "notes": {"kind": "standard", "type": "String"},
        }
        ir = _ir_with_clusters(_minimal_aggregate(fields=fields))
        result = generate_cluster_diagram(ir)
        # No constraint tag — just the type
        assert "+notes String" in result
        assert "~" not in result.split("+notes")[1].split("\n")[0]

    def test_unique_field(self):
        fields = {
            "id": {"kind": "auto", "type": "Auto", "identifier": True},
            "email": {
                "kind": "standard",
                "type": "String",
                "unique": True,
            },
        }
        ir = _ir_with_clusters(_minimal_aggregate(fields=fields))
        result = generate_cluster_diagram(ir)
        assert "+email String~unique~" in result

    def test_display_name_uses_short_name(self):
        """The class label uses the short (unqualified) element name."""
        clusters = _minimal_aggregate(fqn="catalogue.category.Category")
        ir = _ir_with_clusters(clusters)
        result = generate_cluster_diagram(ir)
        assert 'catalogue_category_Category["Category"]' in result
