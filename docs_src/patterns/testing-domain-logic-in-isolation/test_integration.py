# --8<-- [start:persistence]
from isolation_shop.domain import (
    Inventory,
    InventoryEventHandler,
    Order,
    OrderItem,
    OrderPlaced,
    PlaceOrder,
    domain,
)


class TestOrderPersistence:
    def test_order_round_trips_through_repository(self):
        repo = domain.repository_for(Order)

        order = Order(
            customer_id="cust-123",
            total=100.0,
            status="placed",
            items=[OrderItem(product_id="prod-1", quantity=1, unit_price=100.0)],
        )
        repo.add(order)

        retrieved = repo.get(order.order_id)
        assert retrieved.customer_id == "cust-123"
        assert retrieved.total == 100.0
        assert retrieved.status == "placed"


# --8<-- [end:persistence]


# --8<-- [start:handler]
class TestOrderCommandHandlerIntegration:
    def test_place_order_through_handler(self):
        # In sync mode, OrderPlaced reaches InventoryEventHandler too,
        # so the product must be in stock
        inventory_repo = domain.repository_for(Inventory)
        inventory_repo.add(Inventory(product_id="p-1", available_quantity=10))

        domain.process(
            PlaceOrder(
                order_id="ord-123",
                customer_id="cust-456",
                items=[{"product_id": "p-1", "quantity": 1, "unit_price": 50.0}],
                total=50.0,
            )
        )

        order = domain.repository_for(Order).get("ord-123")
        assert order.status == "placed"
        assert inventory_repo.get("p-1").available_quantity == 9


# --8<-- [end:handler]


# --8<-- [start:event_handler]
class TestInventoryReservationIntegration:
    def test_order_placed_triggers_reservation(self):
        # Set up inventory
        inventory_repo = domain.repository_for(Inventory)
        inventory = Inventory(product_id="prod-1", available_quantity=100)
        inventory_repo.add(inventory)

        # Simulate the event
        event = OrderPlaced(
            order_id="ord-123",
            customer_id="cust-456",
            items=[{"product_id": "prod-1", "quantity": 5}],
            total=50.0,
        )

        handler = InventoryEventHandler()
        handler.on_order_placed(event)

        updated = inventory_repo.get("prod-1")
        assert updated.available_quantity == 95


# --8<-- [end:event_handler]
