"""
Sample Protean codebase with multiple anti-patterns for audit demonstration.

This example contains intentional design issues that the audit-domain skill
would detect:
- Logic leak in handler (validation + calculation outside aggregate)
- Primitive obsession (amount + currency fields instead of Money VO)
- Missing events (direct cross-aggregate mutation)
- Scattered validation (checks in handler instead of invariants)

The "after" version is in audit_sample_refactored.py.
"""

from protean import Domain, handle
from protean.fields import Float, HasMany, Integer, String

domain = Domain()


# --- Aggregate: missing value object for money ---


@domain.entity(part_of="Order")
class LineItem:
    product_id = String(required=True)
    quantity = Integer(required=True, min_value=1)
    unit_price_amount = Float(required=True)  # Primitive obsession: should be Money VO
    unit_price_currency = String(
        default="USD"
    )  # Primitive obsession: should be Money VO


@domain.aggregate
class Order:
    customer_id = String(required=True)
    items = HasMany(LineItem)
    total_amount = Float(default=0.0)  # Primitive obsession
    total_currency = String(default="USD")  # Primitive obsession
    status = String(default="DRAFT")

    # Missing: business logic methods like place(), cancel()
    # Missing: invariants for business rules
    # Missing: events for state changes


@domain.aggregate
class Inventory:
    product_id = String(required=True, identifier=True)
    quantity_available = Integer(default=0)


# --- Command ---


@domain.command(part_of="Order")
class PlaceOrder:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)
    unit_price = Float(required=True)


# --- Handler with multiple anti-patterns ---


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        # Anti-pattern: Validation in handler (should be aggregate invariant)
        if command.quantity <= 0:
            raise ValueError("Quantity must be positive")

        # Anti-pattern: Business logic in handler (should be aggregate method)
        total = command.unit_price * command.quantity
        if total > 50000:
            raise ValueError("Order exceeds maximum allowed amount")

        order = Order(
            customer_id=command.customer_id,
            total_amount=total,
            total_currency="USD",
            status="PLACED",
        )
        order.add_items(
            LineItem(
                product_id=command.product_id,
                quantity=command.quantity,
                unit_price_amount=command.unit_price,
                unit_price_currency="USD",
            )
        )
        domain.repository_for(Order).add(order)

        # Anti-pattern: Cross-aggregate mutation in same handler
        inventory = domain.repository_for(Inventory).get(command.product_id)
        inventory.quantity_available -= command.quantity
        domain.repository_for(Inventory).add(inventory)


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        domain.process(
            PlaceOrder(
                customer_id="CUST-001",
                product_id="PROD-001",
                quantity=2,
                unit_price=29.99,
            ),
            asynchronous=False,
        )
