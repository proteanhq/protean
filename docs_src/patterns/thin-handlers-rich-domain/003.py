# --8<-- [start:money]
from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import Float, String

domain = Domain(name="ThinHandlersMoney")


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValidationError({"currency": ["Cannot add different currencies"]})
        return Money(amount=self.amount + other.amount, currency=self.currency)


# --8<-- [end:money]
