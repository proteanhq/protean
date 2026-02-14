from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Post:
    title: Annotated[str, Field(max_length=100)]
    body: str | None = None
    published: bool = False

    def publish(self):
        self.published = True
        self.raise_(PostPublished(post_id=self.id, body=self.body))


@domain.event(part_of=Post)
class PostPublished:
    post_id: str
    body: str | None = None
