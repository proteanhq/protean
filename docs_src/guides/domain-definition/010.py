from protean.domain import Domain
from protean.fields import Float, String, ValueObject

domain = Domain(__name__)


@domain.value_object
class Balance:
    """A composite amount object, containing two parts:
    * currency code - a three letter unique currency code
    * amount - a float value
    """

    currency: String(max_length=3, required=True)
    amount: Float(required=True, min_value=0.0)


@domain.aggregate
class Account:
    balance = ValueObject(Balance)
    name: String(max_length=30)
