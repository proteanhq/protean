"""
Projection with a defaults() method for computed default values.

This example demonstrates:
- Using the defaults() method to set computed default values
- Enum-based choices for String fields
- Conditional default logic based on other field values
- Projections can have behavior limited to defaults and data transformation

Usage:
    building = Building(building_id="BLD-001", name="Tower A", floors=4)
    # defaults() method automatically sets status to "DONE" for 4-floor buildings
"""

from enum import Enum

from protean import Domain
from protean.fields import Identifier, Integer, String

# Domain setup
domain = Domain()


class BuildingStatus(Enum):
    """Enum for building construction status."""

    WIP = "WIP"
    DONE = "DONE"


@domain.projection
class Building:
    """Building projection with computed defaults.

    The defaults() method runs automatically during initialization
    to set computed values based on other fields. This is the only
    behavior that should be in a projection - no business logic.
    """

    building_id: Identifier(identifier=True)
    name: String(max_length=50)
    floors: Integer()
    status: String(choices=BuildingStatus)

    def defaults(self):
        """Set status based on number of floors if not explicitly provided."""
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value


class OrderStatus(Enum):
    """Enum for order statuses."""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


@domain.projection
class OrderSummary:
    """Order summary projection with computed display label.

    Demonstrates defaults() for creating derived display values.
    """

    order_id: Identifier(identifier=True, required=True)
    customer_name: String(max_length=100, required=True)
    item_count: Integer(default=0)
    total_amount: Integer(default=0)
    status: String(choices=OrderStatus, default=OrderStatus.PENDING.value)
    display_label: String(max_length=200)

    def defaults(self):
        """Generate a display label from other fields."""
        if not self.display_label:
            self.display_label = f"Order {self.order_id} - {self.customer_name} ({self.item_count} items)"


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Building with 4 floors gets DONE status automatically
        building1 = Building(building_id="BLD-001", name="Tower A", floors=4)
        print(f"{building1.name}: {building1.status}")
        assert building1.status == "DONE"

        # Building with other floors gets WIP status
        building2 = Building(building_id="BLD-002", name="Tower B", floors=2)
        print(f"{building2.name}: {building2.status}")
        assert building2.status == "WIP"

        # Explicit status overrides defaults
        building3 = Building(
            building_id="BLD-003", name="Tower C", floors=2, status="DONE"
        )
        print(f"{building3.name}: {building3.status}")
        assert building3.status == "DONE"

        # OrderSummary with computed display label
        order = OrderSummary(
            order_id="ORD-001",
            customer_name="Alice",
            item_count=3,
            total_amount=150,
        )
        print(f"Label: {order.display_label}")
        assert "Alice" in order.display_label

        print("Defaults projection working correctly!")
