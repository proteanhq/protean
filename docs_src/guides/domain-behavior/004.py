from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    name: Annotated[str, Field(max_length=50, min_length=3)]
    age: Annotated[int, Field(ge=0, le=120)]
