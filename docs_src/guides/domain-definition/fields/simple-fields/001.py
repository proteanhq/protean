from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    name: Annotated[str, Field(max_length=50, min_length=2)]
