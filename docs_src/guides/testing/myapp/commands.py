from myapp import domain
from myapp.models import (
    Book,
    Inventory,
    Money,
    Order,
    OrderItemVO,
    User,
    UserRegistered,
)
from protean import handle
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, List, String, ValueObject
from protean.utils.globals import current_domain


@domain.command(part_of=User)
class Register:
    user_id: Identifier(identifier=True)
    email: String(max_length=254, required=True)
    name: String(max_length=100, required=True)


@domain.command_handler(part_of=User)
class UserCommandHandler:
    @handle(Register)
    def register(self, command: Register):
        repo = current_domain.repository_for(User)
        if repo.find_by_email(command.email) is not None:
            raise ValidationError({"email": ["already registered"]})

        user = User(id=command.user_id, email=command.email, name=command.name)
        user.raise_(UserRegistered(user_id=user.id, email=user.email, name=user.name))
        repo.add(user)


@domain.command(part_of=Book)
class AddBook:
    title: String(max_length=200, required=True)
    author: String(max_length=150, required=True)
    price_amount: Float(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_id: Identifier(required=True)
    items = List(content_type=ValueObject(OrderItemVO))
    total: Float()


@domain.command_handler(part_of=Book)
class BookCommandHandler:
    @handle(AddBook)
    def add_book(self, command: AddBook):
        book = Book.add(
            title=command.title,
            author=command.author,
            price=Money(amount=command.price_amount),
        )
        current_domain.repository_for(Book).add(book)
        return book.id


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        inventory_repo = current_domain.repository_for(Inventory)
        for item in command.items:
            inventory = inventory_repo.find_by_book(item.book_id)
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError({"items": ["Insufficient stock"]})

        order = Order.place(
            customer_id=command.customer_id, items=command.items, total=command.total
        )
        current_domain.repository_for(Order).add(order)
