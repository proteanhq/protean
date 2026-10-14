# --8<-- [start:discount_policy]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float

domain = Domain(name="ValidationLayeringDiscountPolicy")


@domain.aggregate
class Order:
    discount_percent: Float(min_value=0.0, max_value=100.0)  # Physical range

    @invariant.post
    def discount_within_policy(self):
        if self.discount_percent is not None and self.discount_percent > 50.0:
            raise ValidationError({"discount_percent": ["Discount cannot exceed 50%"]})


# --8<-- [end:discount_policy]

domain.init(traverse=False)
