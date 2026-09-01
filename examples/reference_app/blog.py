"""The canonical golden-path domain for Protean.

A blog ``Post`` that shows the full write-then-read arc with the smallest
domain a reader can hold in their head: a command creates and publishes a
post, an event handler reacts to the publish, and a projector maintains a
read-optimized feed of published posts.

Later pieces of the reference application (the FastAPI app, the docs
quickstart, the README guard) will build on this exact domain. Importing the
module only defines the domain; it does not call ``domain.init()`` or run
the demo. The in-memory demo lives behind the ``if __name__ == "__main__"``
guard so a reader can run it with ``pip install protean`` and nothing else:

    python examples/reference_app/blog.py
"""

# --8<-- [start:quickstart]
# --8<-- [start:imports]
from protean import Domain, current_domain, handle
from protean.core.projector import on
from protean.fields import Identifier, String, Text

domain = Domain()
# --8<-- [end:imports]


# --8<-- [start:aggregate]
@domain.aggregate
class Post:
    title: String(max_length=100, required=True)
    body: Text(required=True)
    status: String(max_length=20, default="DRAFT")

    def publish(self):
        self.status = "PUBLISHED"
        self.raise_(PostPublished(post_id=self.id, title=self.title))


# --8<-- [end:aggregate]
# --8<-- [start:event]
@domain.event(part_of=Post)
class PostPublished:
    post_id: Identifier(required=True)
    title: String(required=True)


# --8<-- [end:event]
# --8<-- [start:command]
@domain.command(part_of=Post)
class PublishPost:
    title: String(max_length=100, required=True)
    body: Text(required=True)


@domain.command_handler(part_of=Post)
class PostCommandHandler:
    @handle(PublishPost)
    def publish_post(self, command: PublishPost):
        post = Post(title=command.title, body=command.body)
        post.publish()
        current_domain.repository_for(Post).add(post)
        return post.id


# --8<-- [end:command]
# --8<-- [start:event_handler]
@domain.event_handler(part_of=Post)
class PostEventHandler:
    @handle(PostPublished)
    def announce(self, event: PostPublished):
        print(f"Event handled: post published ({event.title})")


# --8<-- [end:event_handler]
# --8<-- [start:projection]
@domain.projection
class PublishedPostsFeed:
    """A read-optimized feed of published posts."""

    post_id: Identifier(identifier=True, required=True)
    title: String(max_length=100, required=True)


@domain.projector(projector_for=PublishedPostsFeed, aggregates=[Post])
class PublishedPostsFeedProjector:
    """Maintains the PublishedPostsFeed projection from Post events."""

    @on(PostPublished)
    def on_post_published(self, event: PostPublished):
        feed_entry = PublishedPostsFeed(post_id=event.post_id, title=event.title)
        current_domain.repository_for(PublishedPostsFeed).add(feed_entry)


# --8<-- [end:projection]
# --8<-- [start:usage]
if __name__ == "__main__":
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"

    domain.init(traverse=False)

    with domain.domain_context():
        # Write: publish a post through the command.
        post_id = domain.process(
            PublishPost(title="Hello, Protean!", body="My first published post.")
        )
        post = domain.repository_for(Post).get(post_id)
        print(f"Post created: {post.title} (status: {post.status})")

        # Read: the projector has already filled the feed inline.
        feed = domain.view_for(PublishedPostsFeed).query.all()
        print(f"Published posts feed: {feed.total} row(s)")
        for entry in feed.items:
            print(f"  - {entry.title}")
# --8<-- [end:usage]
# --8<-- [end:quickstart]
