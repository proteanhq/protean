from protean import Domain
from protean.fields import Boolean, Identifier, String, Text

domain = Domain(__file__)


@domain.aggregate
class Post:
    title = String(required=True, max_length=100)
    body = Text()
    published = Boolean(default=False)

    def publish(self):
        self.published = True
        self.raise_(PostPublished(post_id=self.id, body=self.body))


@domain.event(part_of=Post)
class PostPublished:
    post_id = Identifier(required=True)
    body = Text()
