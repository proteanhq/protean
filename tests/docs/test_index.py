"""Check the "See it in action" example on docs/index.md."""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    module = load_example("index/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def test_the_command_handler_creates_a_draft_post(example):
    post_id = example.domain.process(
        example.CreatePost(title="Hello", body="World"), asynchronous=False
    )

    post = example.domain.repository_for(example.Post).get(post_id)
    assert (post.title, post.body, post.status) == ("Hello", "World", "DRAFT")


def test_publishing_a_post_raises_post_published(example):
    post = example.Post(title="Hello", body="World")

    post.publish()

    (event,) = post._events
    assert isinstance(event, example.PostPublished)
    assert (event.post_id, event.title) == (post.id, "Hello")
    assert post.status == "PUBLISHED"
