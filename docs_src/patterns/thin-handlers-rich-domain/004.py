# --8<-- [start:event_handler]
from collections import defaultdict

from protean import Domain, current_domain, handle
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ValidationError
from protean.fields import Auto, Dict, Identifier, Integer, List, String

domain = Domain(name="warehouse")


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    status: String(default="draft")


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    items: List(content_type=Dict)


@domain.aggregate
class Inventory:
    product_id: Identifier(identifier=True)
    available: Integer(default=0)
    reserved: Integer(default=0)
    reserved_for: List(content_type=String)

    def reserve(self, order_id: str, quantities: list[int]) -> None:
        """Reserve stock for an order's lines, once per order."""
        if order_id in self.reserved_for:
            return

        if not quantities:
            raise ValidationError({"quantity": ["An order needs at least one line"]})

        for quantity in quantities:
            if quantity <= 0:
                raise ValidationError(
                    {"quantity": [f"Line quantity {quantity} is not positive"]}
                )

        total = sum(quantities)
        if total > self.available:
            raise ValidationError(
                {"quantity": [f"Only {self.available} units of {self.product_id} left"]}
            )

        self.available -= total
        self.reserved += total
        self.reserved_for = [*self.reserved_for, order_id]


# Thin event handler
@domain.event_handler(part_of=Inventory, stream_category="warehouse::order")
class InventoryEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # reserve() runs once per order, so each product's lines go in one call
        quantities = defaultdict(list)
        for item in event.items:
            quantities[item["product_id"]].append(item["quantity"])

        repo = current_domain.repository_for(Inventory)
        for product_id, product_quantities in quantities.items():
            inventory = repo.get(product_id)
            inventory.reserve(order_id=event.order_id, quantities=product_quantities)
            repo.add(inventory)


# --8<-- [end:event_handler]
