from datetime import date

import pytest

from protean import BaseAggregate
from protean.exceptions import ValidationError
from protean.fields import Date, DateTime, HasMany, Reference, String
from protean.reflection import declared_fields
from protean.utils import fully_qualified_name, utcnow_func


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

    def test_that_abstract_aggregates_get_an_id_field_by_default(self, test_domain):
        @test_domain.aggregate(abstract=True)
        class TimeStamped:
            created_at = DateTime(default=utcnow_func)
            updated_at = DateTime(default=utcnow_func)

        assert "id" in declared_fields(TimeStamped)

    def test_that_an_aggregate_can_opt_to_have_no_id_field_by_default(
        self, test_domain
    ):
        @test_domain.aggregate(auto_add_id_field=False)
        class TimeStamped:
            created_at = DateTime(default=utcnow_func)
            updated_at = DateTime(default=utcnow_func)

        assert "id" not in declared_fields(TimeStamped)

    def test_that_abstract_aggregates_can_have_an_explicit_id_field(self, test_domain):
        @test_domain.aggregate(abstract=True)
        class User(BaseAggregate):
            email = String(identifier=True)
            name = String(max_length=55)

        assert "email" in declared_fields(User)


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

        @test_domain.entity(part_of=Post)
        class Comment:
            content = String(max_length=500)
            post = Reference("Post")

        test_domain.init(traverse=False)

        post = Post(name="The World")
        test_domain.repository_for(Post).add(post)

        post.add_comments(Comment(content="This is a great post!"))
        test_domain.repository_for(Post).add(post)

        refreshed_post = test_domain.repository_for(Post).get(post.id)
        print([c for c in refreshed_post.comments])
