from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float

domain = Domain(name="PercentageValueObject")


# --8<-- [start:percentage]
@domain.value_object
class Percentage:
    value: Float(required=True)

    @invariant.post
    def must_be_between_zero_and_hundred(self):
        if not (0 <= self.value <= 100):
            raise ValidationError({"value": ["Percentage must be between 0 and 100"]})


# --8<-- [end:percentage]

domain.init(traverse=False)
