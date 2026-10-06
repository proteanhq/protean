"""Entities take no ``abstract`` option; shared fields go on a ``BaseEntity`` base.

``abstract=True`` is an aggregate option. On an entity it raises
``ConfigurationError``. The entity skill teaches inheritance through an
undecorated ``BaseEntity`` subclass that holds the shared fields, with only the
concrete subclasses registered.
"""

import pytest

from protean.core.entity import BaseEntity
from protean.exceptions import ConfigurationError
from protean.fields import HasMany, String
from protean.utils.reflection import declared_fields


def test_registering_an_entity_with_abstract_raises(test_domain):
    @test_domain.aggregate
    class Post:
        title = String()

    class Comment(BaseEntity):
        body = String()

    with pytest.raises(ConfigurationError) as exc:
        test_domain.register(Comment, part_of=Post, abstract=True)

    assert "Unknown option" in str(exc.value)
    assert "abstract" in str(exc.value)


def test_decorating_an_entity_with_abstract_raises(test_domain):
    @test_domain.aggregate
    class Post:
        title = String()

    with pytest.raises(ConfigurationError) as exc:

        @test_domain.entity(part_of=Post, abstract=True)
        class Comment:
            body = String()

    assert "Unknown option" in str(exc.value)
    assert "abstract" in str(exc.value)


def test_concrete_entities_inherit_fields_from_an_undecorated_base(test_domain):
    @test_domain.aggregate
    class Post:
        title = String()
        comments = HasMany("Comment")
        reactions = HasMany("Reaction")

    class Authored(BaseEntity):
        author = String(max_length=50, required=True)

    @test_domain.entity(part_of=Post)
    class Comment(Authored):
        body = String()

    @test_domain.entity(part_of=Post)
    class Reaction(Authored):
        emoji = String(max_length=8)

    test_domain.init(traverse=False)

    assert "author" in declared_fields(Comment)
    assert "author" in declared_fields(Reaction)
    entity_names = {record.name for record in test_domain.registry.entities.values()}
    assert entity_names == {"Comment", "Reaction"}

    post = Post(
        title="Hello",
        comments=[Comment(author="Ada", body="Nice")],
        reactions=[Reaction(author="Lin", emoji="+1")],
    )
    assert post.comments[0].author == "Ada"
    assert post.reactions[0].author == "Lin"
