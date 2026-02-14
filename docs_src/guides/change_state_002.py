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


domain.init(traverse=False)
with domain.domain_context():
    post = Post(
        id="1",
        title="A Great Post",
        body="This is the body of a great post",
        comments=[
            Comment(id="1", content="Amazing!", rating=5.0),
            Comment(id="2", content="Great!", rating=4.5),
        ],
    )

    # This persists one `Post` record and two `Comment` records
    domain.repository_for(Post).add(post)
