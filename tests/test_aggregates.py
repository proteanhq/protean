from datetime import date, datetime

import pytest

from protean import BaseAggregate
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Date, DateTime, HasMany, Reference, String
from protean.reflection import declared_fields
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

        p1 = Person(email="john.doe@example.com")
        test_domain.repository_for(Person).add(p1)
        p2 = Person(email="john.doe@example.com")

        with pytest.raises(ValidationError):
            test_domain.repository_for(Person).add(p2)


class TestAggregateInitialization:
    pass


class TestAggregateIdentity:
    # FIXME This should fail
    def test_exception_on_multiple_identifiers(self, test_domain):
        @test_domain.aggregate
        class Person:
            email = String(identifier=True)
            username = String(identifier=True)

    def test_that_abstract_aggregates_do_not_have_id_field(self, test_domain):
        @test_domain.aggregate
        class TimeStamped:
            created_at = DateTime(default=datetime.utcnow)
            updated_at = DateTime(default=datetime.utcnow)

            class Meta:
                abstract = True

        assert "id" not in declared_fields(TimeStamped)

    def test_that_abstract_aggregates_cannot_have_a_declared_id_field(
        self, test_domain
    ):
        with pytest.raises(IncorrectUsageError) as exception:

            @test_domain.aggregate
            class User(BaseAggregate):
                email = String(identifier=True)
                name = String(max_length=55)

                class Meta:
                    abstract = True

        assert exception.value.messages == {
            "_entity": [
                "Abstract Aggregate `User` marked as abstract cannot have identity fields"
            ]
        }


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
            created_on = Date(default=date.today)

            comments = HasMany("Comment")

        @test_domain.entity
        class Comment:
            content = String(max_length=500)
            post = Reference("Post")

            class Meta:
                aggregate_cls = Post

        post = Post(name="The World")
        test_domain.repository_for(Post).add(post)

        post.add_comments(Comment(content="This is a great post!"))
        test_domain.repository_for(Post).add(post)

        refreshed_post = test_domain.repository_for(Post).get(post.id)
        print([c for c in refreshed_post.comments])
