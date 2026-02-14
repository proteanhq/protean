from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Book:
    title: Annotated[str, Field(max_length=255)] | None = None
    content: str
