from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import DateTime, Identifier, String, Text
from protean.fields.basic import Boolean
from protean.utils import utcnow_func
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

published_count = 0


class Create(BaseCommand):
    id = Identifier(identifier=True)
    topic = String()
    content = Text()


class Created(BaseEvent):
    id = Identifier(identifier=True)
    topic = String()
    content = Text()


class Published(BaseEvent):
    id = Identifier(required=True)
    published_time = DateTime(default=utcnow_func)


class Post(BaseAggregate):
    topic = String()
    content = Text()
    is_published = Boolean(default=False)

    @classmethod
    def initialize(cls, identifier, topic, content):
        post = Post(id=identifier, topic=topic, content=content)
        post.raise_(Created(id=identifier, topic=topic, content=content))
        return post

    def publish(self):
        # Perform some heavy validations
        if not self.is_published:
            self.raise_(Published(id=self.id))

    @apply
    def created(self, event: Created):
        self.topic = event.topic
        self.content = event.content

    @apply
    def mark_published(self, _: Published) -> None:
        self.is_published = True


class PostCommandHandler(BaseCommandHandler):
    @handle(Create)
    def create_new_post(self, command: Create):
        post = Post.initialize(command.id, command.topic, command.content)
        current_domain.repository_for(Post).add(post)


class PostEventHandler(BaseEventHandler):
    @handle(Created)
    def check_and_publish(self, event: Created):
        repo = current_domain.repository_for(Post)
        post = repo.get(event.id)

        # Do some intensive work to verify post content

        # ... and then publish
        post.publish()
        repo.add(post)


class Metrics(BaseEventHandler):
    @handle(Published)
    def record_publishing(self, _: Published) -> None:
        global published_count
        published_count += 1


@pytest.mark.eventstore
def test_nested_uow_processing(test_domain):
    test_domain.register(Post, is_event_sourced=True)
    test_domain.register(Create, part_of=Post)
    test_domain.register(Created, part_of=Post)
    test_domain.register(Published, part_of=Post)
    test_domain.register(PostEventHandler, part_of=Post)
    test_domain.register(Metrics, stream_category="test::post")
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    PostCommandHandler().create_new_post(
        Create(id=identifier, topic="foo", content="bar")
    )

    global published_count
    assert published_count == 1
