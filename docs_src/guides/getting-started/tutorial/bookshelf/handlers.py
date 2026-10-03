# --8<-- [start:handlers]
from bookshelf import domain
from bookshelf.commands import AddBook, ConfirmOrder, PlaceOrder, ShipOrder
from bookshelf.events import BookAdded, OrderConfirmed, OrderShipped
from bookshelf.models import Book, Inventory, Money, Order, OrderItem
from protean import handle
from protean.fields import Identifier
from protean.utils.globals import current_domain


@domain.command_handler(part_of=Book)
class BookCommandHandler:
    @handle(AddBook)
    def add_book(self, command: AddBook) -> Identifier:
        book = Book(
            title=command.title,
            author=command.author,
            isbn=command.isbn,
            price=Money(amount=command.price_amount),
            description=command.description,
        )
        book.add_to_catalog()
        current_domain.repository_for(Book).add(book)
        return book.id


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> Identifier:
        order = Order(
            customer_name=command.customer_name,
            items=[
                OrderItem(
                    book_title=command.book_title,
                    quantity=command.quantity,
                    unit_price=Money(amount=command.unit_price_amount),
                ),
            ],
        )
        current_domain.repository_for(Order).add(order)
        return order.id

    @handle(ConfirmOrder)
    def confirm_order(self, command: ConfirmOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.confirm()
        repo.add(order)

    @handle(ShipOrder)
    def ship_order(self, command: ShipOrder) -> None:
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.ship()
        repo.add(order)


@domain.event_handler(part_of=Book)
class BookEventHandler:
    @handle(BookAdded)
    def on_book_added(self, event: BookAdded):
        inventory = Inventory(
            book_id=event.book_id,
            title=event.title,
            quantity=10,
        )
        current_domain.repository_for(Inventory).add(inventory)


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderConfirmed)
    def on_order_confirmed(self, event: OrderConfirmed):
        print(
            f"  [Notification] Order {event.order_id} confirmed for {event.customer_name}"
        )

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        print(
            f"  [Notification] Order {event.order_id} shipped to {event.customer_name}"
        )


# --8<-- [end:handlers]
