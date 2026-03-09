"""Tests for description (docstring) extraction across all domain element types."""

import pytest

from protean.ir.builder import IRBuilder

from .elements import build_description_test_domain


@pytest.fixture
def desc_ir():
    """Return the full IR for the description test domain."""
    domain = build_description_test_domain()
    return IRBuilder(domain).build()


@pytest.fixture
def order_cluster(desc_ir):
    """Return the Order aggregate's cluster."""
    for cluster in desc_ir["clusters"].values():
        if cluster["aggregate"]["name"] == "Order":
            return cluster
    pytest.fail("Order cluster not found")


@pytest.mark.no_test_domain
class TestClusterElementDescriptions:
    """Verify description is captured for elements within aggregate clusters."""

    def test_aggregate_description(self, order_cluster):
        assert (
            order_cluster["aggregate"]["description"]
            == "An order placed by a customer."
        )

    def test_entity_description(self, order_cluster):
        entity = next(iter(order_cluster["entities"].values()))
        assert entity["description"] == "A single item within an order."

    def test_value_object_description(self, order_cluster):
        vo = next(iter(order_cluster["value_objects"].values()))
        assert vo["description"] == "A postal address."

    def test_command_description(self, order_cluster):
        cmd = next(iter(order_cluster["commands"].values()))
        assert cmd["description"] == "Request to place a new order."

    def test_event_description(self, order_cluster):
        # Find the user-defined event (not fact events)
        for evt in order_cluster["events"].values():
            if evt["name"] == "OrderPlaced":
                assert (
                    evt["description"]
                    == "Emitted when an order is successfully placed."
                )
                return
        pytest.fail("OrderPlaced event not found")

    def test_command_handler_description(self, order_cluster):
        ch = next(iter(order_cluster["command_handlers"].values()))
        assert ch["description"] == "Handles order commands."

    def test_event_handler_description(self, order_cluster):
        eh = next(iter(order_cluster["event_handlers"].values()))
        assert eh["description"] == "Reacts to order events."

    def test_application_service_description(self, order_cluster):
        svc = next(iter(order_cluster["application_services"].values()))
        assert svc["description"] == "Application service for order use cases."

    def test_repository_description(self, order_cluster):
        repo = next(iter(order_cluster["repositories"].values()))
        assert repo["description"] == "Custom repository for orders."


@pytest.mark.no_test_domain
class TestFlowElementDescriptions:
    """Verify description is captured for flow elements (domain services, subscribers)."""

    def test_domain_service_description(self, desc_ir):
        ds = next(iter(desc_ir["flows"]["domain_services"].values()))
        assert ds["description"] == "Validates orders across business rules."

    def test_subscriber_description(self, desc_ir):
        sub = next(iter(desc_ir["flows"]["subscribers"].values()))
        assert sub["description"] == "Consumes external payment events."


@pytest.mark.no_test_domain
class TestProjectionElementDescriptions:
    """Verify description is captured for projection-related elements."""

    def test_projection_description(self, desc_ir):
        proj_group = next(iter(desc_ir["projections"].values()))
        assert (
            proj_group["projection"]["description"] == "Read-optimized order summary."
        )

    def test_projector_description(self, desc_ir):
        proj_group = next(iter(desc_ir["projections"].values()))
        projector = next(iter(proj_group["projectors"].values()))
        assert projector["description"] == "Projects order events into OrderSummary."

    def test_query_description(self, desc_ir):
        proj_group = next(iter(desc_ir["projections"].values()))
        query = next(iter(proj_group["queries"].values()))
        assert query["description"] == "Query to fetch an order summary."

    def test_query_handler_description(self, desc_ir):
        proj_group = next(iter(desc_ir["projections"].values()))
        qh = next(iter(proj_group["query_handlers"].values()))
        assert qh["description"] == "Handles order summary queries."


@pytest.mark.no_test_domain
class TestDescriptionOmittedWhenEmpty:
    """Verify description is omitted (sparse) when element has no docstring."""

    def test_no_description_when_no_docstring(self):
        """Elements without docstrings should not have a description key."""
        from .elements import build_command_event_test_domain

        domain = build_command_event_test_domain()
        ir = IRBuilder(domain).build()

        # PlaceOrder in this domain has no docstring
        for cluster in ir["clusters"].values():
            for cmd in cluster["commands"].values():
                if cmd["name"] == "PlaceOrder":
                    assert "description" not in cmd
                    return
        pytest.fail("PlaceOrder command not found")
