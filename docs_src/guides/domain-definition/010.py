# --8<-- [start:full]
from protean.domain import Domain
from protean.fields import Decimal, String, ValueObject

domain = Domain()


@domain.value_object
class Balance:
    """A composite amount object, containing two parts:
    * currency code - a three letter unique currency code
    * amount - a decimal value
    """

    currency: String(max_length=3, required=True)
    amount: Decimal(precision=19, scale=4, required=True, min_value=0)


@domain.aggregate
class Account:
    balance = ValueObject(Balance)
    name: String(max_length=30)


# --8<-- [end:full]
