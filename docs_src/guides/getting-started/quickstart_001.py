from protean import Domain, handle, invariant
from protean.exceptions import ValidationError
from protean.utils.globals import current_domain
from typing import Annotated
from pydantic import Field

domain = Domain()


# --8<-- [start:aggregate]
@domain.aggregate
class Post:
    title: Annotated[str, Field(max_length=100)]
    body: str
    status: Annotated[str, Field(max_length=20)] = "DRAFT"

    def publish(self):
        self.status = "PUBLISHED"
        self.raise_(PostPublished(post_id=self.id, title=self.title))

    @invariant.post
    def body_must_be_substantial_when_published(self):
        if self.status == "PUBLISHED" and (not self.body or len(self.body) < 10):
            raise ValidationError(
                {"body": ["A post must have at least 10 characters to publish."]}
            )


# --8<-- [end:aggregate]


# --8<-- [start:event]
@domain.event(part_of="Post")
class PostPublished:
    post_id: str
    title: str


# --8<-- [end:event]


# --8<-- [start:command]
@domain.command(part_of="Post")
class CreatePost:
    title: Annotated[str, Field(max_length=100)]
    body: str


# --8<-- [end:command]


# --8<-- [start:command_handler]
@domain.command_handler(part_of=Post)
class PostCommandHandler:
    @handle(CreatePost)
    def create_post(self, command: CreatePost):
        post = Post(title=command.title, body=command.body)
        current_domain.repository_for(Post).add(post)
        return post.id


# --8<-- [end:command_handler]


# --8<-- [start:event_handler]
@domain.event_handler(part_of=Post)
class PostEventHandler:
    @handle(PostPublished)
    def on_post_published(self, event: PostPublished):
        print(f"Post published: {event.title}")


# --8<-- [end:event_handler]


# --8<-- [start:usage]
if __name__ == "__main__":
    domain.init()

    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    with domain.domain_context():
        # Create a post via command
        post_id = domain.process(
            CreatePost(title="Hello, Protean!", body="My first domain.")
        )

        # Retrieve it from the repository
        post = domain.repository_for(Post).get(post_id)
        print(f"Post: {post.title} (status: {post.status})")

        # Publish the post — this raises a PostPublished event
        post.publish()
        domain.repository_for(Post).add(post)

        # Verify
        updated = domain.repository_for(Post).get(post_id)
        print(f"Updated: {updated.title} (status: {updated.status})")
# --8<-- [end:usage]
