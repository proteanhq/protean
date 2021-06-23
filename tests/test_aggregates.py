import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.exceptions import ValidationError
from protean.core.field.basic import Integer, String
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
