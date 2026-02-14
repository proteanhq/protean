from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    name: Annotated[str, Field(max_length=50)]
    age: int = 21
    country: Annotated[str, Field(max_length=2)] | None = None
