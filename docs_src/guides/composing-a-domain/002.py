from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class User:
    first_name: Annotated[str, Field(max_length=50)] | None = None
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int | None = None
