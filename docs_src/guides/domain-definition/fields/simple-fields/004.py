from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Account:
    name: Annotated[str, Field(max_length=255)] | None = None
    balance: float = 0.0
