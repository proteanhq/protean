from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


class User(BaseAggregate):
    first_name: Annotated[str, Field(max_length=50)] | None = None
    last_name: Annotated[str, Field(max_length=50)] | None = None
    age: int | None = None


domain.register(User, stream_category="account")
