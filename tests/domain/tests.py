# Protean
import pytest

from protean import Domain
from protean.core.exceptions import ConfigurationError, IncorrectUsageError
from protean.utils import fully_qualified_name

# Local/Relative Imports
from .elements import UserStructAggregate, UserStructEntity, UserStructFoo, UserStructRequestObject, UserStructVO


class TestDomainInitialization:

    def test_that_a_domain_can_be_initialized_successfully(self):
        domain = Domain(__name__)
        assert domain is not None
        assert domain.registry is not None
        assert domain.aggregates == {}


class TestDomainRegistration:

    def test_that_only_recognized_element_types_can_be_registered(self, test_domain):

        with pytest.raises(NotImplementedError):
            test_domain.registry.register_element(UserStructFoo)

    def test_register_aggregate_with_domain(self, test_domain):
        test_domain.registry.register_element(UserStructAggregate)

        assert test_domain.aggregates != {}
        assert fully_qualified_name(UserStructAggregate) in test_domain.aggregates

    def test_register_entity_with_domain(self, test_domain):
        test_domain.registry.register_element(UserStructEntity)

        assert fully_qualified_name(UserStructEntity) in test_domain.entities

    def test_register_value_object_with_domain(self, test_domain):
        test_domain.registry.register_element(UserStructVO)

        assert fully_qualified_name(UserStructVO) in test_domain.value_objects

    def test_register_request_object_with_domain(self, test_domain):
        test_domain.registry.register_element(UserStructRequestObject)

        assert fully_qualified_name(UserStructRequestObject) in test_domain.request_objects

    @pytest.mark.xfail(reason='Temporarily disabled raising ConfigurationError - Need to control with flag')
    def test_that_registering_an_element_again_raises_configuration_error(self, test_domain):
        test_domain.registry.register_element(UserStructRequestObject)

        assert fully_qualified_name(UserStructRequestObject) in test_domain.request_objects

        with pytest.raises(ConfigurationError):
            test_domain.registry.register_element(UserStructRequestObject)

    def test_that_a_properly_subclassed_entity_can_be_directly_registered(self, test_domain):
        from protean.core.entity import BaseEntity
        from protean.core.field.basic import String

        class FooBar(BaseEntity):
            foo = String(max_length=50)

        test_domain.register(FooBar)

        assert fully_qualified_name(FooBar) in test_domain.entities

    def test_that_a_properly_subclassed_aggregate_can_be_directly_registered(self, test_domain):
        from protean.core.aggregate import BaseAggregate
        from protean.core.field.basic import String

        class FooBar(BaseAggregate):
            foo = String(max_length=50)

        test_domain.register(FooBar)

        assert fully_qualified_name(FooBar) in test_domain.aggregates

    def test_that_an_improperly_subclassed_element_cannot_be_registered(self, test_domain):
        from protean.core.field.basic import String

        class Foo:
            pass

        class Bar(Foo):
            foo = String(max_length=50)

        with pytest.raises(NotImplementedError):
            test_domain.register(Bar)


class TestDomainAnnotations:

    def test_auto_register_aggregate_with_annotation(self, test_domain):
        from protean.core.field.basic import String

        @test_domain.aggregate
        class FooBar:
            foo = String(max_length=50)

        assert fully_qualified_name(FooBar) in test_domain.aggregates

    def test_auto_register_entity_with_annotation(self, test_domain):
        from protean.core.field.basic import String

        @test_domain.entity
        class FooBar:
            foo = String(max_length=50)

        assert fully_qualified_name(FooBar) in test_domain.entities

    def test_auto_register_request_object_with_annotation(self, test_domain):
        from protean.core.field.basic import String

        @test_domain.request_object
        class FooBar:
            foo = String(max_length=50)

        assert fully_qualified_name(FooBar) in test_domain.request_objects

    def test_auto_register_value_object_with_annotation(self, test_domain):
        from protean.core.field.basic import String

        @test_domain.value_object
        class FooBar:
            foo = String(max_length=50)

        assert fully_qualified_name(FooBar) in test_domain.value_objects

    def test_register_entity_against_an_aggregate(self, test_domain):
        from protean.core.field.basic import String

        @test_domain.entity(aggregate_cls='foo')
        class FooBar:
            foo = String(max_length=50)

        assert FooBar.meta_.aggregate_cls == 'foo'

    def test_that_only_recognized_element_types_can_be_registered(self, test_domain):
        from enum import Enum
        from protean.core.field.basic import String

        class DummyElement(Enum):
            FOO = 'FOO'

        class FooBar:
            foo = String(max_length=50)

        with pytest.raises(IncorrectUsageError):
            test_domain._register_element(DummyElement.FOO, FooBar, aggregate_cls='foo')
