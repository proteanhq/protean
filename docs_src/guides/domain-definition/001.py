from protean.domain import Domain
from datetime import date
from typing import Annotated
from pydantic import Field

publishing = Domain()


@publishing.aggregate
class Post:
    name: Annotated[str, Field(max_length=50)] | None = None
    created_on: date | None = None
