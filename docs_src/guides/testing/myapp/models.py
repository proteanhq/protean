from myapp import domain
from protean import handle
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, Integer, List, String, ValueObject
from protean.utils.globals import current_domain


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")


@domain.value_object
class OrderItemVO:
    book_id: Identifier(required=True)
    quantity: Integer(min_value=1, required=True)


# --8<-- [start:user]
@domain.aggregate
class User:
    name: String(max_length=100, required=True)
    email: String(max_length=254)
    status: String(max_length=20, default="INACTIVE")

    def activate(self):
        if not self.email:
            raise ValidationError({"email": ["email required for activation"]})
        self.status = "ACTIVE"


# --8<-- [end:user]


@domain.event(part_of=User)
class UserRegistered:
    user_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


@domain.repository(part_of=User)
class UserRepository:
    def find_by_email(self, email):
        return self.query.filter(email=email).all().first


@domain.aggregate
class Notification:
    recipient: String(max_length=254, required=True)
    kind: String(max_length=50, required=True)


@domain.event_handler(part_of=User)
class WelcomeNotifier:
    @handle(UserRegistered)
    def send_welcome(self, event: UserRegistered):
        current_domain.repository_for(Notification).add(
            Notification(recipient=event.email, kind="welcome")
        )


@domain.event(part_of="Book")
class BookAdded:
    book_id: Identifier(required=True)
    title: String(required=True)
    price: Float(required=True)


@domain.aggregate
class Book:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price = ValueObject(Money)

    @classmethod
    def add(cls, title, author, price):
        book = cls(title=title, author=author, price=price)
        book.raise_(BookAdded(book_id=book.id, title=title, price=price.amount))
        return book


@domain.aggregate
class Inventory:
    book_id: Identifier(required=True)
    title: String(max_length=200)
    quantity: Integer(min_value=0, default=0)

    def remove(self, quantity):
        self.quantity -= quantity


@domain.repository(part_of=Inventory)
class InventoryRepository:
    def find_by_book(self, book_id):
        return self.query.filter(book_id=book_id).all().first


@domain.aggregate
class Customer:
    name: String(max_length=100, required=True)
    order_history = List(content_type=Identifier)

    def record_order(self, order_id):
        self.order_history = [*self.order_history, order_id]


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemVO))


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemVO))
    total: Float()
    status: String(max_length=20, default="PENDING")

    @classmethod
    def place(cls, customer_id, items, total=None):
        order = cls(
            customer_id=customer_id, items=items, total=total, status="CONFIRMED"
        )
        order.raise_(
            OrderPlaced(order_id=order.id, customer_id=customer_id, items=items)
        )
        return order


@domain.event_handler(part_of=Order)
class StockKeeper:
    """Takes the ordered copies out of stock."""

    @handle(OrderPlaced)
    def remove_ordered_copies(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.find_by_book(item.book_id)
            inventory.remove(item.quantity)
            repo.add(inventory)


@domain.event_handler(part_of=Order)
class OrderHistoryRecorder:
    """Adds each order to the history of the customer who placed it."""

    @handle(OrderPlaced)
    def record(self, event: OrderPlaced):
        repo = current_domain.repository_for(Customer)
        customer = repo.get(event.customer_id)
        customer.record_order(event.order_id)
        repo.add(customer)


@domain.projection
class BookCatalog:
    book_id: Identifier(identifier=True)
    title: String(max_length=200, required=True)
    price: Float()
    copies_sold: Integer(default=0)


@domain.projector(projector_for=BookCatalog, aggregates=[Book, Order])
class BookCatalogProjector:
    @handle(BookAdded)
    def add_to_catalog(self, event: BookAdded):
        current_domain.repository_for(BookCatalog).add(
            BookCatalog(book_id=event.book_id, title=event.title, price=event.price)
        )

    @handle(OrderPlaced)
    def count_sold_copies(self, event: OrderPlaced):
        repo = current_domain.repository_for(BookCatalog)
        for item in event.items:
            entry = repo.query.filter(book_id=item.book_id).all().first
            if entry is not None:
                entry.copies_sold += item.quantity
                repo.add(entry)
