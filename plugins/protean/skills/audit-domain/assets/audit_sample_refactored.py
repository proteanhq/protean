"""
Refactored version of the sample codebase — all anti-patterns resolved.

Changes from audit_sample_codebase.py:
1. Extracted Money value object (fixes primitive obsession)
2. Moved business logic into aggregate methods (fixes logic leak)
3. Added invariants for business rules (fixes scattered validation)
4. Added domain events (fixes missing events)
5. Order's own event handler reacts to OrderPlaced and sends a ReserveStock
   command, and Inventory's command handler reserves the stock (fixes
   transaction boundary violation)
6. Used string references for part_of (fixes circular import risk)

Events are delivered at least once, so ReserveStock carries the order id and
Inventory records the order ids it has already reserved stock for. A repeat
returns without changes.
"""

from protean import Domain, current_domain, handle, invariant
from protean.fields import (
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)

domain = Domain()

# Run the hop in-process: OrderPlaced reaches its handler when the unit of work
# that saves the order commits, and ReserveStock reaches its handler as soon as
# it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


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
    """Stock for one product.

    `reserved_order_ids` records which orders have already reserved stock.
    Reserving is an update, so the stock level alone cannot show whether a given
    order was applied; this list can.
    """

    product_id = String(required=True, identifier=True)
    quantity_available = Integer(default=0)
    reserved_order_ids = List(content_type=String)

    def reserve(self, order_id: str, quantity: int) -> None:
        """Reserve stock for one order and record that the order was applied."""
        if self.quantity_available < quantity:
            from protean.exceptions import ValidationError

            raise ValidationError({"quantity": ["Insufficient stock"]})
        self.quantity_available -= quantity
        self.reserved_order_ids = [*self.reserved_order_ids, order_id]


# --- Commands ---


@domain.command(part_of="Order")
class PlaceOrder:
    customer_id = String(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)
    unit_price = Float(required=True)


@domain.command(part_of="Inventory")
class ReserveStock:
    """Reserve stock for one placed order.

    `order_id` comes from the event, so a redelivered event reissues the same
    command and the handler can tell it has already applied it.
    """

    order_id = Identifier(required=True)
    product_id = String(required=True)
    quantity = Integer(required=True)


# --- Thin command handlers (one aggregate each) ---


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
        current_domain.repository_for(Order).add(order)


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReserveStock)
    def reserve_stock(self, command: ReserveStock) -> None:
        repo = current_domain.repository_for(Inventory)
        inventory = repo.get(command.product_id)
        if command.order_id in inventory.reserved_order_ids:
            # Already applied. A redelivered OrderPlaced reissues ReserveStock,
            # and reserving again would take the stock down twice.
            return
        inventory.reserve(command.order_id, command.quantity)
        repo.add(inventory)


# --- Event handler in Order's cluster (hands off with a command) ---


@domain.event_handler(part_of=Order)
class OrderEventsHandler:
    """React to Order's own OrderPlaced event and ask Inventory to reserve stock.

    The handler sits in Order's cluster, because it reacts to Order's own event.
    Inventory's command handler does the write, in its own transaction.
    """

    @handle(OrderPlaced)
    def reserve_inventory(self, event: OrderPlaced) -> None:
        current_domain.process(
            ReserveStock(
                order_id=event.order_id,
                product_id=event.product_id,
                quantity=event.quantity,
            )
        )


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(Inventory).add(
            Inventory(product_id="PROD-001", quantity_available=10)
        )
        domain.process(
            PlaceOrder(
                customer_id="CUST-001",
                product_id="PROD-001",
                quantity=2,
                unit_price=29.99,
            ),
        )
