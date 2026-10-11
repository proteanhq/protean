# --8<-- [start:post]
from protean import Domain, handle
from protean.fields import Identifier, String, Text
from protean.utils.globals import current_domain

domain = Domain()  # (1)!


@domain.aggregate  # (2)!
class Post:
    title: String(max_length=100, required=True)
    body: Text(required=True)
    status: String(max_length=20, default="DRAFT")

    def publish(self):
        self.status = "PUBLISHED"
        self.raise_(PostPublished(post_id=self.id, title=self.title))  # (3)!


@domain.event(part_of="Post")  # (4)!
class PostPublished:
    post_id: Identifier(required=True)
    title: String(required=True)


@domain.command(part_of="Post")  # (5)!
class CreatePost:
    title: String(max_length=100, required=True)
    body: Text(required=True)


@domain.command_handler(part_of=Post)  # (6)!
class PostCommandHandler:
    @handle(CreatePost)
    def create_post(self, command: CreatePost):
        post = Post(title=command.title, body=command.body)
        current_domain.repository_for(Post).add(post)  # (7)!
        return post.id


# --8<-- [end:post]
