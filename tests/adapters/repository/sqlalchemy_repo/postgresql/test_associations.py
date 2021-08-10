from datetime import datetime

import pytest

from protean.core import BaseAggregate, BaseEntity
from protean.core.field.association import HasMany, Reference
from protean.core.field.basic import DateTime, Text
from protean.core.unit_of_work import UnitOfWork


class Comment(BaseEntity):
    content = Text()
    added_on = DateTime()

    post = Reference("Post")

    class Meta:
        aggregate_cls = "Post"


class Post(BaseAggregate):
    content = Text(required=True)
    comments = HasMany(Comment)


@pytest.mark.postgresql
def test_updating_a_has_many_association(test_domain):
    test_domain.register(Post)
    test_domain.register(Comment)

    post_repo = test_domain.repository_for(Post)
    post = Post(content="bar")
    post.add_comments(Comment(content="foo", added_on=datetime.utcnow()))
    post_repo.add(post)

    with UnitOfWork():
        refreshed_post = post_repo.get(post.id)
        assert refreshed_post is not None

        refreshed_comment = refreshed_post.comments[0]
        assert refreshed_comment is not None

        refreshed_comment.content = "baz"
        refreshed_post.add_comments(refreshed_comment)
        post_repo.add(refreshed_post)
