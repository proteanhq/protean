from protean import Domain, invariant
from protean.exceptions import ValidationError
from typing import Annotated
from pydantic import Field

domain = Domain(__name__)


@domain.value_object
class Balance:
    currency: Annotated[str, Field(max_length=3)]
    amount: float

    @invariant.post
    def check_balance_is_positive_if_currency_is_USD(self):
        if self.amount < 0 and self.currency == "USD":
            raise ValidationError({"balance": ["Balance cannot be negative for USD"]})
