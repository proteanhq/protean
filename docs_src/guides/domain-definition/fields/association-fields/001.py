from protean import Domain
from protean.fields import HasOne
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Book:
    title: Annotated[str, Field(max_length=100)]
    author = HasOne("Author")


@domain.entity(part_of="Book")
class Author:
    name: Annotated[str, Field(max_length=50)]
