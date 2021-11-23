from datetime import datetime

import pytest

from protean import BaseAggregate, BaseEntity, BaseValueObject, UnitOfWork
from protean.fields import DateTime, Dict, HasMany, Reference, Text, ValueObject


class Comment(BaseEntity):
    content = Text()
    added_on = DateTime()

    post = Reference("Post")

    class Meta:
        aggregate_cls = "Post"


class Post(BaseAggregate):
    content = Text(required=True)
    comments = HasMany(Comment)


class Permission(BaseValueObject):
    dict_object = Dict()


class Audit(BaseAggregate):
    permission = ValueObject(Permission)


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


@pytest.mark.postgresql
def test_embedded_dict_field_in_value_object(test_domain):
    test_domain.register(Audit)

    audit_repo = test_domain.repository_for(Audit)
    audit = Audit(permission=Permission(dict_object={"foo": "bar"}))
    audit_repo.add(audit)

    assert test_domain.repository_for(Audit).get(audit.id).permission_dict_object == {
        "foo": "bar"
    }
