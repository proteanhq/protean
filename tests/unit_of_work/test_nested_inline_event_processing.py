from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest

from protean import (
    BaseCommand,
    BaseCommandHandler,
    BaseEvent,
    BaseEventHandler,
    BaseEventSourcedAggregate,
    apply,
    handle,
)
from protean.fields import DateTime, Identifier, String, Text
from protean.fields.basic import Boolean
from protean.globals import current_domain

published_count = 0


class Published(BaseEvent):
    id = Identifier(required=True)
    published_time = DateTime(default=datetime.utcnow)


class Post(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
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

    @apply(Published)
    def mark_published(self, _: BaseEvent) -> None:
        self.is_published = True


class Create(BaseCommand):
    id = Identifier(identifier=True)
    topic = String()
    content = Text()

    class Meta:
        aggregate_cls = Post


class Created(BaseEvent):
    id = Identifier(identifier=True)
    topic = String()
    content = Text()


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

    class Meta:
        stream_name = "post"


@pytest.mark.eventstore
def test_nested_uow_processing(test_domain):
    test_domain.register(Post)
    test_domain.register(PostEventHandler, aggregate_cls=Post)
    test_domain.register(Metrics)

    identifier = str(uuid4())
    PostCommandHandler().create_new_post(
        Create(id=identifier, topic="foo", content="bar")
    )

    global published_count
    assert published_count == 1
