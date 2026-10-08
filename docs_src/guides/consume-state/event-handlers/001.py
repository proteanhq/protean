# --8<-- [start:import-handle]
from protean import handle

# --8<-- [end:import-handle]
# isort: split

# --8<-- [start:multiple-handlers]
from protean import Domain, current_domain
from protean.fields import Identifier, Integer, String

domain = Domain(name="Bookshop")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.aggregate
class Order:
    book_id: Identifier(required=True)
    quantity: Integer(required=True)
    status: String(default="PLACED")

    def place(self):
        self.raise_(
            OrderPlaced(order_id=self.id, book_id=self.book_id, quantity=self.quantity)
        )

    def ship(self):
        self.status = "SHIPPED"
        self.raise_(
            OrderShipped(order_id=self.id, book_id=self.book_id, quantity=self.quantity)
        )

    def cancel(self):
        self.status = "CANCELLED"
        self.raise_(
            OrderCancelled(
                order_id=self.id, book_id=self.book_id, quantity=self.quantity
            )
        )


@domain.command(part_of="Inventory")
class ReduceStock:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.command(part_of="Inventory")
class RestoreStock:
    order_id: Identifier(required=True)
    book_id: Identifier(required=True)
    quantity: Integer(required=True)


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    in_stock: Integer(required=True)


@domain.event_handler(part_of=Order)
class ManageInventory:
    @handle(OrderShipped)
    def reduce_stock(self, event: OrderShipped):
        current_domain.process(
            ReduceStock(
                order_id=event.order_id,
                book_id=event.book_id,
                quantity=event.quantity,
            )
        )

    @handle(OrderCancelled)
    def restore_stock(self, event: OrderCancelled):
        current_domain.process(
            RestoreStock(
                order_id=event.order_id,
                book_id=event.book_id,
                quantity=event.quantity,
            )
        )


# --8<-- [end:multiple-handlers]


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    @handle(ReduceStock)
    def reduce_stock(self, command: ReduceStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(book_id=command.book_id)
        inventory.in_stock -= command.quantity
        repo.add(inventory)

    @handle(RestoreStock)
    def restore_stock(self, command: RestoreStock):
        repo = current_domain.repository_for(Inventory)
        inventory = repo.find_by(book_id=command.book_id)
        inventory.in_stock += command.quantity
        repo.add(inventory)
