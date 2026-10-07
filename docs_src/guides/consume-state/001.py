# --8<-- [start:full]
from protean import Domain, current_domain, handle
from protean.fields import Identifier, Integer, List, String

domain = Domain()
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)
    total_amount: Integer(required=True)


@domain.command(part_of="Inventory")
class ReduceStock:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.aggregate
class Order:
    book_id: Identifier(required=True)
    quantity: Integer(required=True)
    total_amount: Integer(required=True)
    status: String(choices=["PENDING", "SHIPPED", "DELIVERED"], default="PENDING")

    def ship_order(self):
        self.status = "SHIPPED"

        self.raise_(  # (1)
            OrderShipped(
                order_id=self.id,
                book_id=self.book_id,
                quantity=self.quantity,
                total_amount=self.total_amount,
            )
        )


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    in_stock: Integer(required=True)
    applied_order_ids: List(content_type=String)

    def reduce_stock(self, order_id: str, quantity: int) -> None:
        self.in_stock -= quantity
        self.applied_order_ids = [*self.applied_order_ids, order_id]


@domain.event_handler(part_of=Order)  # (2)
class ManageInventory:
    @handle(OrderShipped)
    def reduce_stock_level(self, event: OrderShipped):
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                book_id=event.book_id,
                quantity=event.quantity,
            )
        )


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(book_id=command.book_id)

        if command.order_id in inventory.applied_order_ids:  # (3)
            return

        inventory.reduce_stock(command.order_id, command.quantity)  # (4)
        repo.add(inventory)


domain.init()
with domain.domain_context():
    # Persist Order
    order = Order(book_id="book-1", quantity=10, total_amount=100)
    domain.repository_for(Order).add(order)

    # Persist Inventory
    inventory = Inventory(book_id="book-1", in_stock=100)
    domain.repository_for(Inventory).add(inventory)

    # Ship Order
    order.ship_order()
    domain.repository_for(Order).add(order)

    # Verify that Inventory Level has been reduced
    stock = domain.repository_for(Inventory).get(inventory.id)
    print(stock.to_dict())
    assert stock.in_stock == 90

    # A repeated delivery of the same order leaves the stock alone
    domain.process(ReduceStock(order_id=order.id, book_id="book-1", quantity=10))
    assert domain.repository_for(Inventory).get(inventory.id).in_stock == 90
# --8<-- [end:full]
