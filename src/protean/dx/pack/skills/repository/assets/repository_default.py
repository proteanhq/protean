"""
Default repository usage - no custom repository class needed.

This example demonstrates:
- Protean auto-generates a repository for every aggregate
- Using domain.repository_for(Aggregate) to access the default repository
- Adding (persisting) aggregates with repo.add()
- Loading aggregates by identifier with repo.get()
- Repository handles both create and update via add()
- Aggregates with default status and state transitions

Usage:
    repo = domain.repository_for(Order)
    repo.add(order)
    loaded = repo.get("ORD-001")
"""

from protean import Domain
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """Order aggregate with basic fields and status transitions."""

    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float(default=0.0)
    status: String(default="draft")

    def place(self, total_amount: float):
        """Place the order with the given total amount."""
        if self.status != "draft":
            raise ValueError("Only draft orders can be placed")
        self.total_amount = total_amount
        self.status = "placed"

    def cancel(self):
        """Cancel the order."""
        if self.status == "cancelled":
            raise ValueError("Order is already cancelled")
        self.status = "cancelled"


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Access the auto-generated repository
        repo = domain.repository_for(Order)

        # Create and persist a new order
        order = Order(order_id="ORD-001", customer_id="CUST-123")
        repo.add(order)
        print(f"Persisted order: {order.order_id}, status={order.status}")

        # Load the order back from the repository
        loaded_order = repo.get("ORD-001")
        print(f"Loaded order: {loaded_order.order_id}, status={loaded_order.status}")

        # Modify and re-persist (add handles updates too)
        loaded_order.place(total_amount=99.99)
        repo.add(loaded_order)
        print(f"Updated order: {loaded_order.order_id}, status={loaded_order.status}")
