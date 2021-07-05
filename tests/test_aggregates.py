import pytest

from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.core.exceptions import ValidationError
from protean.core.field.basic import Integer, String, Date
from protean.core.field.association import HasMany
from protean.utils import fully_qualified_name


class TestAggregateRegistration:
    def test_defining_aggregate_with_domain_decorator(self, test_domain):
        @test_domain.aggregate
        class Post(BaseAggregate):
            name = String(max_length=50)

        assert fully_qualified_name(Post) in test_domain.registry.aggregates

    def test_manual_registration_of_aggregate_with_domain(self, test_domain):
        class Post(BaseAggregate):
            name = String(max_length=50)

        test_domain.register(Post)

        assert fully_qualified_name(Post) in test_domain.registry.aggregates


class TestAggregateFieldDeclarations:
    pass


class TestAggregateFieldOptions:
    def test_unique_validation(self, test_domain):
        @test_domain.aggregate
        class Person:
            email = String(unique=True)

        p1 = Person(name="John Doe", email="john.doe@example.com")
        test_domain.repository_for(Person).add(p1)
        p2 = Person(name="Jane Doe", email="john.doe@example.com")

        with pytest.raises(ValidationError):
            test_domain.repository_for(Person).add(p2)


class TestAggregateInitialization:
    pass


class TestAggregateIdentity:
    pass


class TestAggregateMeta:
    class TestAggregateMetaInClassDefinition:
        pass

    class TestAggregateMetaSuppliedInDecorator:
        pass


class TestAggregateAssociations:
    def test_has_many(self, test_domain):
        @test_domain.aggregate
        class Post:
            name = String(max_length=50)
            created_on = Date(default=datetime.utcnow)

            comments = HasMany("Comment")

        @test_domain.entity
        class Comment:
            content = String(max_length=500)

            class Meta:
                aggregate_cls = Post

        post = Post(name="The World")
        test_domain.repository_for(Post).add(post)

        post.comments.add(Comment(content="This is a great post!"))
        test_domain.repository_for(Post).add(post)

        refreshed_post = test_domain.repository_for(Post).get(post.id)
        print([c for c in refreshed_post.comments])
