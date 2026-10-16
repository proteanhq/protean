# --8<-- [start:level2]
from ecommerce.domain import Inventory, OrderDashboard, PlaceOrder, domain


class TestOrderFlowSync:
    """Level 2: Test the full chain with sync event processing."""

    def test_place_order_updates_projection(self):
        """Command -> handler -> aggregate -> event -> projector -> projection."""
        domain.repository_for(Inventory).add(
            Inventory(product_id="prod-1", available_quantity=100)
        )

        domain.process(
            PlaceOrder(
                order_id="ord-001",
                customer_id="cust-123",
                product_id="prod-1",
                total=99.95,
            )
        )

        # Projection is updated synchronously -- no sleep, no engine
        view = domain.view_for(OrderDashboard)
        dashboard = view.get("ord-001")

        assert dashboard.status == "placed"
        assert dashboard.customer_id == "cust-123"
        assert dashboard.total == 99.95

    def test_event_chain_fires_downstream_handlers(self):
        """Verify that OrderPlaced triggers InventoryEventHandler."""
        repo = domain.repository_for(Inventory)
        repo.add(Inventory(product_id="prod-1", available_quantity=100))

        domain.process(
            PlaceOrder(
                order_id="ord-003",
                customer_id="cust-123",
                product_id="prod-1",
                quantity=2,
                total=50.0,
            )
        )

        # In sync mode, the InventoryEventHandler fires inline
        # during the same UoW commit that persists the Order
        inventory = repo.get("prod-1")
        assert inventory.available_quantity == 98
        assert inventory.reserved_quantity == 2


# --8<-- [end:level2]
