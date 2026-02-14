from protean.domain import Domain
from protean.fields import ValueObject
from typing import Annotated
from pydantic import Field

domain = Domain(__name__)


@domain.value_object
class Balance:
    """A composite amount object, containing two parts:
    * currency code - a three letter unique currency code
    * amount - a float value
    """

    currency: Annotated[str, Field(max_length=3)]
    amount: Annotated[float, Field(ge=0.0)]


@domain.aggregate
class Account:
    balance = ValueObject(Balance)
    name: Annotated[str, Field(max_length=30)] | None = None
