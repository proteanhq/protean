"""
Refactored version of the sample codebase — all anti-patterns resolved.

Changes from audit_sample_codebase.py:
1. Extracted Money value object (fixes primitive obsession)
2. Moved business logic into aggregate methods (fixes logic leak)
3. Added invariants for business rules (fixes scattered validation)
4. Added domain events (fixes missing events)
5. Used event handler for cross-aggregate sync (fixes transaction boundary violation)
6. Used string references for part_of (fixes circular import risk)
"""

from protean import Domain, handle, invariant
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject

domain = Domain()


# --- Value Object: extracted from primitive fields ---


@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(max_length=3, default="USD")

    def multiply(self, factor: int) -> "Money":
        return Money(amount=self.amount * factor, currency=self.currency)


# --- Entities ---


@domain.entity(part_of="Order")
class LineItem:
    product_id = String(required=True)
    quantity = Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)


# --- Events ---


@domain.event(part_of="Order")
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)
    total_amount = Float(required=True)


# --- Aggregate with business logic ---


@domain.aggregate
class Order:
    customer_id = String(required=True)
    items = HasMany(LineItem)
    total = ValueObject(Money)
    status = String(default="DRAFT")

    def place(self, product_id: str, quantity: int, unit_price: Money) -> None:
        """Place the order with the given line item."""
        line_item = LineItem(
            product_id=product_id,
            quantity=quantity,
            unit_price=unit_price,
        )
        self.add_items(line_item)
        self.total = unit_price.multiply(quantity)
        self.status = "PLACED"

        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_id=self.customer_id,
                product_id=product_id,
                quantity=quantity,
                total_amount=self.total.amount,
            )
        )

    @invariant.post
    def order_total_must_not_exceed_maximum(self):
        """Orders cannot exceed $50,000."""
        if self.total and self.total.amount > 50000:
            from protean.exceptions import ValidationError

            raise ValidationError({"total": ["Order total cannot exceed $50,000"]})


# --- Inventory aggregate (separate transaction boundary) ---


@domain.aggregate
class Inventory:
    product_id = String(required=True, identifier=True)
    quantity_available = Integer(default=0)

    def reserve(self, quantity: int) -> None:
        """Reserve stock for an order."""
        if self.quantity_available < quantity:
            from protean.exceptions import ValidationError

            raise ValidationError({"quantity": ["Insufficient stock"]})
        self.quantity_available -= quantity


# --- Command ---


@domain.command(part_of="Order")
class PlaceOrder:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)
    unit_price = Float(required=True)


# --- Thin command handler ---


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order(customer_id=command.customer_id)
        price = Money(amount=command.unit_price)
        order.place(
            product_id=command.product_id,
            quantity=command.quantity,
            unit_price=price,
        )
        domain.repository_for(Order).add(order)


# --- Event handler for cross-aggregate sync (separate transaction) ---


@domain.event_handler(part_of=Inventory, stream_category=Order.meta_.stream_category)
class OrderEventsHandler:
    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced) -> None:
        inventory = domain.repository_for(Inventory).get(event.product_id)
        inventory.reserve(event.quantity)
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
