from decimal import Decimal as D

from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Decimal, String

domain = Domain(name="Banking")


@domain.value_object
class Balance:
    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True)

    @invariant.post
    def check_balance_is_positive_if_currency_is_USD(self):
        if self.amount < 0 and self.currency == "USD":
            raise ValidationError({"balance": ["Balance cannot be negative for USD"]})


# --8<-- [start:replace]
balance = Balance(currency="USD", amount=D("100.00"))

try:
    balance.replace(amount=D("-100.00"))
except ValidationError as exc:
    print(exc.messages)  # {'balance': ['Balance cannot be negative for USD']}
# --8<-- [end:replace]

# --8<-- [start:unknown]
from protean.exceptions import IncorrectUsageError

try:
    balance.replace(nonexistent=42)
except IncorrectUsageError as exc:
    print(exc)  # Unknown field(s) for Balance: nonexistent
# --8<-- [end:unknown]
