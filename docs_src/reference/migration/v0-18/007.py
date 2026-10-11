from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(default=0.0)

    @invariant.post
    def total_is_not_negative(self):
        if self.total < 0:
            raise ValidationError({"total": ["Total cannot be negative"]})


# --8<-- [start:rollback]
def rejected_total():
    order = Order(customer_id="c1", total=10)
    try:
        order.total = -5  # breaks a post-invariant
    except ValidationError as exc:
        print("rejected:", exc.messages)

    return order.total  # 0.17: -5.0. 0.18: 10.0


# --8<-- [end:rollback]
