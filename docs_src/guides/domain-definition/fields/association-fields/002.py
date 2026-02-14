from protean import Domain
from protean.fields import HasMany
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Post:
    title: Annotated[str, Field(max_length=100)]
    body: str | None = None
    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content: Annotated[str, Field(max_length=50)]
    rating: Annotated[float, Field(le=5)] | None = None
