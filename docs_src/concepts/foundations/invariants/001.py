from protean import Domain
from protean.fields import Float, HasMany

domain = Domain(name="InvariantsConcept")


# --8<-- [start:model]
from protean import invariant
from protean.exceptions import ValidationError


@domain.aggregate
class Order:
    total_amount = Float(required=True)
    items = HasMany("OrderItem")

    @invariant.post
    def total_must_equal_sum_of_items(self):
        expected = sum(item.subtotal for item in self.items)
        if self.total_amount != expected:
            raise ValidationError({"_entity": ["Total should be sum of item prices"]})


@domain.entity(part_of=Order)
class OrderItem:
    subtotal = Float(required=True)


def change_total_alone():
    order = Order(
        total_amount=100.0,
        items=[OrderItem(subtotal=60.0), OrderItem(subtotal=40.0)],
    )

    try:
        # This raises ValidationError -- the invariant fires immediately
        order.total_amount = 50.0  # But items sum to 100.0
    except ValidationError as exc:
        print(exc.messages["_entity"])  # ['Total should be sum of item prices']

    return order.total_amount  # Still 100.0


# --8<-- [end:model]


# --8<-- [start:atomic_change]
from protean.core.aggregate import atomic_change


def change_total_with_items(order):
    with atomic_change(order):
        order.total_amount = 120.0  # Would fail invariant alone
        order.add_items(OrderItem(subtotal=20))  # But together they're consistent
    # Invariants checked ONCE on exit -- both changes are valid together


# --8<-- [end:atomic_change]
