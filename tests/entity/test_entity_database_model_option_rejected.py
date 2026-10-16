"""Entities take no ``database_model`` option.

A custom model is registered with ``@domain.database_model(part_of=<Entity>)``.
Passing ``database_model=`` to the entity itself raises ``ConfigurationError``.
"""

import pytest

from protean.core.entity import BaseEntity
from protean.exceptions import ConfigurationError
from protean.fields import HasMany, String


def test_registering_an_entity_with_database_model_raises(test_domain):
    @test_domain.aggregate
    class Post:
        title = String()

    class Comment(BaseEntity):
        body = String()

    with pytest.raises(ConfigurationError) as exc:
        test_domain.register(Comment, part_of=Post, database_model="CommentModel")

    assert "Unknown option" in str(exc.value)
    assert "database_model" in str(exc.value)


def test_decorating_an_entity_with_database_model_raises(test_domain):
    @test_domain.aggregate
    class Post:
        title = String()

    with pytest.raises(ConfigurationError) as exc:

        @test_domain.entity(part_of=Post, database_model="CommentModel")
        class Comment:
            body = String()

    assert "Unknown option" in str(exc.value)
    assert "database_model" in str(exc.value)


def test_an_entity_without_the_option_registers(test_domain):
    @test_domain.aggregate
    class Post:
        title = String()
        comments = HasMany("Comment")

    @test_domain.entity(part_of=Post)
    class Comment:
        body = String()

    assert Comment.meta_.part_of is Post
    assert "database_model" not in dict(Comment.meta_)
