# --8<-- [start:full]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Decimal, String

domain = Domain()


@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    @invariant.post
    def check_balance_is_positive_if_currency_is_USD(self):
        if self.amount < 0 and self.currency == "USD":
            raise ValidationError({"balance": ["Balance cannot be negative for USD"]})


# --8<-- [end:full]
