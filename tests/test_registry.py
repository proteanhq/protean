from datetime import datetime
from enum import Enum

import inflection
import pytest

from protean import BaseAggregate, BaseEntity
from protean.domain.registry import _DomainRegistry
from protean.fields import DateTime, Identifier, Integer, String
from protean.utils import DomainObjects


class User(BaseAggregate):
    first_name = String(max_length=50)
    last_name = String(max_length=50)
    age = Integer()
    role_id = Identifier()


class Role(BaseEntity):
    name = String(max_length=15, required=True)
    created_on = DateTime(default=datetime.today())

    class Meta:
        aggregate_cls = User


def test_element_registration():
    register = _DomainRegistry()
    register.register_element(User)

    assert (
        "tests.test_registry.User" in register._elements[DomainObjects.AGGREGATE.value]
    )


def test_delisting_element():
    register = _DomainRegistry()
    register.register_element(User)

    assert (
        "tests.test_registry.User" in register._elements[DomainObjects.AGGREGATE.value]
    )

    register.delist_element(User)

    assert (
        "tests.test_registry.User"
        not in register._elements[DomainObjects.AGGREGATE.value]
    )


def test_fetching_elements_from_registry():
    register = _DomainRegistry()
    register.register_element(User)

    assert "tests.test_registry.User" in register.aggregates


def test_that_registry_exposes_properties():
    # Assert that lowercased, underscored, pluralized methods
    # are attached to registry for each element type
    assert all(
        inflection.pluralize(inflection.underscore(element_type.value.lower()))
        for element_type in DomainObjects
    )


def test_that_registering_an_unknown_element_type_triggers_an_error():
    class DummyEnum(Enum):
        UNKNOWN = "UNKNOWN"

    class FooBar1:
        element_type = "FOOBAR"

    class FooBar2:
        element_type = DummyEnum.UNKNOWN

    class FooBar3:
        pass

    register = _DomainRegistry()

    with pytest.raises(NotImplementedError):
        register.register_element(FooBar1)

    with pytest.raises(NotImplementedError):
        register.register_element(FooBar2)

    with pytest.raises(NotImplementedError):
        register.register_element(FooBar3)


def test_that_delisting_an_unknown_element_type_triggers_an_error():
    class DummyEnum(Enum):
        UNKNOWN = "UNKNOWN"

    class FooBar1:
        element_type = "FOOBAR"

    class FooBar2:
        element_type = DummyEnum.UNKNOWN

    class FooBar3:
        pass

    register = _DomainRegistry()

    with pytest.raises(NotImplementedError):
        register.delist_element(FooBar1)

    with pytest.raises(NotImplementedError):
        register.delist_element(FooBar2)

    with pytest.raises(NotImplementedError):
        register.delist_element(FooBar3)


def test_that_re_registering_an_element_has_no_effect():
    register = _DomainRegistry()
    register.register_element(User)
    register.register_element(User)

    assert len(register._elements[DomainObjects.AGGREGATE.value]) == 1
    assert (
        "tests.test_registry.User" in register._elements[DomainObjects.AGGREGATE.value]
    )


def test_properties_method_returns_a_dictionary_of_all_protean_elements():
    from protean.domain.registry import properties

    assert properties() == {
        "aggregates": DomainObjects.AGGREGATE.value,
        "application_services": DomainObjects.APPLICATION_SERVICE.value,
        "command_handlers": DomainObjects.COMMAND_HANDLER.value,
        "commands": DomainObjects.COMMAND.value,
        "domain_services": DomainObjects.DOMAIN_SERVICE.value,
        "emails": DomainObjects.EMAIL.value,
        "entities": DomainObjects.ENTITY.value,
        "event_handlers": DomainObjects.EVENT_HANDLER.value,
        "event_sourced_aggregates": DomainObjects.EVENT_SOURCED_AGGREGATE.value,
        "event_sourced_repositories": DomainObjects.EVENT_SOURCED_REPOSITORY.value,
        "events": DomainObjects.EVENT.value,
        "models": DomainObjects.MODEL.value,
        "repositories": DomainObjects.REPOSITORY.value,
        "serializers": DomainObjects.SERIALIZER.value,
        "subscribers": DomainObjects.SUBSCRIBER.value,
        "value_objects": DomainObjects.VALUE_OBJECT.value,
        "views": DomainObjects.VIEW.value,
    }


def test_domain_record_repr():
    record = _DomainRegistry.DomainRecord(
        name="User",
        qualname="tests.test_registry.User",
        class_type=DomainObjects.AGGREGATE.value,
        cls=User,
    )

    assert repr(record) == "<class User: tests.test_registry.User (AGGREGATE)>"


def test_elements_in_registry():
    """Test that `domain.registry.elements` is a graph of all registered elements"""
    register = _DomainRegistry()
    register.register_element(User)
    register.register_element(Role)

    assert len(register.elements) == 2
    assert register.elements == {
        "aggregates": [User],
        "entities": [Role],
    }


def test_domain_registry_elements_repr():
    register = _DomainRegistry()
    register.register_element(User)
    register.register_element(Role)

    assert repr(register.elements) == (
        "{'aggregates': [<class 'tests.test_registry.User'>], "
        "'entities': [<class 'tests.test_registry.Role'>]}"
    )
