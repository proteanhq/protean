# --8<-- [start:fields]
from protean import Domain
from protean.fields import Float, HasMany, Identifier, Integer, String

domain = Domain(name="AlwaysValidFields")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    items = HasMany("OrderItem")


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.01)


# --8<-- [end:fields]


# --8<-- [start:field_checks]
from protean.exceptions import ValidationError


def show_field_checks():
    # Missing required field → ValidationError
    try:
        Order()  # customer_id is required
    except ValidationError as exc:
        print(exc.messages)  # {'customer_id': ['is required']}

    # Type violation → ValidationError
    try:
        OrderItem(product_name="Widget", quantity="abc", unit_price=10.0)
    except ValidationError as exc:
        print(exc.messages)  # {'quantity': ['Input should be a valid integer, ...']}

    # Range violation → ValidationError
    try:
        OrderItem(product_name="Widget", quantity=0, unit_price=10.0)
    except ValidationError as exc:
        print(exc.messages)  # quantity must be >= 1

    # Even after construction, assignments are checked
    item = OrderItem(product_name="Widget", quantity=1, unit_price=10.0)
    try:
        item.unit_price = -5.0  # min_value is 0.01
    except ValidationError as exc:
        print(exc.messages)  # {'unit_price': ['Input should be greater than ...']}


# --8<-- [end:field_checks]
