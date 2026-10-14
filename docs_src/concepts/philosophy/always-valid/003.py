# --8<-- [start:setup]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject

domain = Domain(name="AlwaysValidAggregates")


# --8<-- [end:setup]


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(required=True, max_length=3)


# --8<-- [start:aggregate]
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    status: String(max_length=20, default="draft")
    total = ValueObject(Money)
    items = HasMany("OrderItem")

    @invariant.post
    def must_have_items_when_placed(self):
        if self.status != "draft" and not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})

    @invariant.post
    def total_must_match_items(self):
        if self.items and self.total:
            expected = sum(item.quantity * item.unit_price for item in self.items)
            if abs(self.total.amount - expected) > 0.01:
                message = (
                    f"Total {self.total.amount} does not match items total {expected}"
                )
                raise ValidationError({"total": [message]})


@domain.entity(part_of=Order)
class OrderItem:
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.01)


# --8<-- [end:aggregate]


# --8<-- [start:invariant_checks]
def show_invariant_checks():
    # After construction
    try:
        Order(
            customer_id="cust-1",
            status="confirmed",  # not draft, but no items → ValidationError
        )
    except ValidationError as exc:
        print(exc.messages["items"])  # ['Order must have at least one item']

    # After every field assignment
    order = Order(customer_id="cust-1")
    try:
        order.status = "confirmed"  # triggers post-invariants → checks items
    except ValidationError as exc:
        print(exc.messages["items"])  # ['Order must have at least one item']

    # Recursively through child entities
    order.add_items(OrderItem(product_name="Widget", quantity=2, unit_price=10.0))
    # Post-invariants run on the aggregate root, checking all rules
    order.status = "confirmed"  # Now valid: the order has an item
    return order


# --8<-- [end:invariant_checks]


# --8<-- [start:atomic_change]
from protean.core.aggregate import atomic_change


def change_total_and_items():
    order = Order(
        customer_id="cust-1",
        total=Money(amount=20.0, currency="USD"),
        items=[OrderItem(product_name="Widget", quantity=2, unit_price=10.0)],
    )

    with atomic_change(order):
        order.total = Money(amount=120.0, currency="USD")  # Would fail alone
        order.add_items(OrderItem(product_name="Gadget", quantity=4, unit_price=25.0))
    # Invariants checked ONCE on exit -- both changes valid together
    return order


# --8<-- [end:atomic_change]
