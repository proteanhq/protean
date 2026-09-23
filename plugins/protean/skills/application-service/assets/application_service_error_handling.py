"""
Application service demonstrating error handling patterns.

This example demonstrates:
- Exceptions propagating directly to the caller (no handle_error hook)
- UnitOfWork auto-rollback on failure
- Domain validation errors from aggregates
- Caller-side error handling patterns

Usage:
    svc = OrderApplicationServices()
    try:
        order_id = svc.place_order(customer_id="CUST-001", items=["item1"])
    except ValidationError:
        ...  # Handle domain validation error
"""

from protean import Domain, current_domain, use_case
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, Integer, String

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """Order aggregate with business rule enforcement."""

    customer_id: String(required=True)
    item_count: Integer(default=0)
    total_amount: Float(default=0.0)
    status: String(choices=["DRAFT", "PLACED", "CANCELLED"], default="DRAFT")

    @classmethod
    def place(cls, customer_id: str, items: list):
        """Factory method that enforces the 'orders must have items' rule.

        Raises:
            ValidationError: If no items are provided.
        """
        if not items:
            raise ValidationError({"items": ["Order must have at least one item"]})

        order = cls(
            customer_id=customer_id,
            item_count=len(items),
            total_amount=sum(items),
        )
        order.status = "PLACED"
        return order

    def cancel(self):
        """Cancel the order.

        Raises:
            ValidationError: If the order is already cancelled.
        """
        if self.status == "CANCELLED":
            raise ValidationError({"status": ["Order is already cancelled"]})
        self.status = "CANCELLED"


@domain.application_service(part_of=Order)
class OrderApplicationServices:
    """Application service demonstrating error handling.

    Exceptions propagate directly to the caller. There is no
    handle_error hook like command/event handlers have.
    The UnitOfWork automatically rolls back on failure.
    """

    @use_case
    def place_order(self, customer_id: str, items: list) -> Identifier:
        """Place a new order.

        The aggregate's factory method enforces business rules.
        If validation fails, the exception propagates and the
        UnitOfWork rolls back any partial changes.
        """
        order = Order.place(customer_id=customer_id, items=items)
        current_domain.repository_for(Order).add(order)
        return order.id

    @use_case
    def cancel_order(self, order_id: Identifier) -> None:
        """Cancel an existing order.

        Loads the order and cancels it. If the order is already
        cancelled, the aggregate raises a ValidationError.
        """
        order = current_domain.repository_for(Order).get(order_id)
        order.cancel()
        current_domain.repository_for(Order).add(order)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        svc = OrderApplicationServices()

        # Successful order placement
        order_id = svc.place_order(customer_id="CUST-001", items=[10.00, 20.00, 15.00])
        print(f"Order placed: {order_id}")

        # Attempting to place an order with no items — raises ValidationError
        try:
            svc.place_order(customer_id="CUST-002", items=[])
        except ValidationError as exc:
            print(f"Validation error: {exc.messages}")

        # Cancel the order
        svc.cancel_order(order_id=order_id)
        print("Order cancelled")

        # Attempting to cancel again — raises ValidationError
        try:
            svc.cancel_order(order_id=order_id)
        except ValidationError as exc:
            print(f"Cancel error: {exc.messages}")
