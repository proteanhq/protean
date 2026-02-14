from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain(__name__)


@domain.value_object
class Balance:
    currency: Annotated[str, Field(max_length=3)]
    amount: float
