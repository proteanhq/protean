from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, String

domain = Domain(__name__)


@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Float(required=True)

    @invariant.post
    def check_balance_is_positive_if_currency_is_USD(self):
        if self.amount < 0 and self.currency == "USD":
            raise ValidationError({"balance": ["Balance cannot be negative for USD"]})
