import pytest

from protean import Domain
from protean.exceptions import IncorrectUsageError
from protean.utils import EventStrategy, fully_qualified_name

from .elements import UserAggregate, UserEntity, UserFoo, UserVO


class TestDomainInitialization:
    def test_that_a_domain_can_be_initialized_successfully(self):
        domain = Domain(__name__)
        assert domain is not None
        assert domain.registry is not None
        if domain.config["EVENT_STRATEGY"] == EventStrategy.DB_SUPPORTED.value:
            assert len(domain.registry.aggregates) == 2
            assert "protean.infra.eventing.EventLog" in domain.registry.aggregates
            assert "protean.infra.job.Job" in domain.registry.aggregates
        else:
            assert domain.registry.aggregates == {}


class TestDomainRegistration:
    def test_that_only_recognized_element_types_can_be_registered(self, test_domain):

        with pytest.raises(NotImplementedError):
            test_domain.registry.register_element(UserFoo)

    def test_register_aggregate_with_domain(self, test_domain):
        test_domain.registry.register_element(UserAggregate)

        assert test_domain.registry.aggregates != {}
        assert fully_qualified_name(UserAggregate) in test_domain.registry.aggregates

    def test_register_entity_with_domain(self, test_domain):
        test_domain.registry.register_element(UserEntity)

        assert fully_qualified_name(UserEntity) in test_domain.registry.entities

    def test_register_value_object_with_domain(self, test_domain):
        test_domain.registry.register_element(UserVO)

        assert fully_qualified_name(UserVO) in test_domain.registry.value_objects

    def test_that_an_improperly_subclassed_element_cannot_be_registered(
        self, test_domain
    ):
        from protean.core.field.basic import String

        class Foo:
            pass

        class Bar(Foo):
            foo = String(max_length=50)

        with pytest.raises(NotImplementedError):
            test_domain.register(Bar)


class TestDomainAnnotations:
    # Individual test cases for registering domain elements with
    #   domain decorators are present in their respective test folders.

    def test_that_only_recognized_element_types_can_be_registered(self, test_domain):
        # Standard Library Imports
        from enum import Enum

        from protean.core.field.basic import String

        class DummyElement(Enum):
            FOO = "FOO"

        class FooBar:
            foo = String(max_length=50)

        with pytest.raises(IncorrectUsageError):
            test_domain._register_element(DummyElement.FOO, FooBar, aggregate_cls="foo")
