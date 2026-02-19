from datetime import datetime
from enum import Enum

import inflection
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.domain.registry import _DomainRegistry
from protean.exceptions import NotSupportedError
from protean.fields import DateTime, Identifier, Integer, String
from protean.utils import DomainObjects


class User(BaseAggregate):
    first_name: String(max_length=50)
    last_name: String(max_length=50)
    age: Integer()
    role_id: Identifier()


class Role(BaseEntity):
    name: String(max_length=15, required=True)
    created_on: DateTime(default=datetime.today())


def test_element_registration():
    register = _DomainRegistry()
    register.register_element(User)

    assert (
        "tests.test_registry.User" in register._elements[DomainObjects.AGGREGATE.value]
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

    with pytest.raises(NotSupportedError):
        register.register_element(FooBar1)

    with pytest.raises(NotSupportedError):
        register.register_element(FooBar2)

    with pytest.raises(NotSupportedError):
        register.register_element(FooBar3)


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
        "event_sourced_repositories": DomainObjects.EVENT_SOURCED_REPOSITORY.value,
        "events": DomainObjects.EVENT.value,
        "database_models": DomainObjects.DATABASE_MODEL.value,
        "process_managers": DomainObjects.PROCESS_MANAGER.value,
        "repositories": DomainObjects.REPOSITORY.value,
        "subscribers": DomainObjects.SUBSCRIBER.value,
        "value_objects": DomainObjects.VALUE_OBJECT.value,
        "projections": DomainObjects.PROJECTION.value,
        "projectors": DomainObjects.PROJECTOR.value,
    }


def test_domain_registry_repr():
    register = _DomainRegistry()
    register.register_element(User)
    register.register_element(Role)

    assert repr(register) == (
        "<DomainRegistry: "
        "{'aggregates': [<class 'tests.test_registry.User'>], "
        "'entities': [<class 'tests.test_registry.Role'>]}>"
    )


def test_domain_record_repr():
    from protean.domain.registry import DomainRecord

    record = DomainRecord(
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


def test_domain_registry_is_serializable():
    """Test that _DomainRegistry and its instances can be serialized"""
    import pickle

    # Test empty registry serialization
    register = _DomainRegistry()
    serialized = pickle.dumps(register)
    deserialized = pickle.loads(serialized)
    assert isinstance(deserialized, _DomainRegistry)
    assert deserialized.elements == {}

    # Test registry with elements
    register.register_element(User)
    register.register_element(Role)

    serialized = pickle.dumps(register)
    deserialized = pickle.loads(serialized)

    assert isinstance(deserialized, _DomainRegistry)
    assert len(deserialized.elements) == 2
    assert deserialized.elements == {
        "aggregates": [User],
        "entities": [Role],
    }


def test_internal_elements_are_not_exposed_in_public_properties():
    """Test that elements marked as internal are not exposed through public properties"""
    register = _DomainRegistry()

    # Register a public element
    register.register_element(User, internal=False)

    # Register an internal element
    register.register_element(Role, internal=True)

    # Public properties should only contain non-internal elements
    assert len(register.aggregates) == 1
    assert "tests.test_registry.User" in register.aggregates

    # Entities should be empty since Role is internal
    assert len(register.entities) == 0

    # But internal elements should still be in the raw _elements
    assert len(register._elements[DomainObjects.ENTITY.value]) == 1
    assert len(register._elements[DomainObjects.AGGREGATE.value]) == 1


def test_internal_elements_not_in_elements_property():
    """Test that internal elements don't appear in the elements property"""
    register = _DomainRegistry()

    # Register both internal and public elements
    register.register_element(User, internal=False)
    register.register_element(Role, internal=True)

    # Elements property should only contain public elements
    elements = register.elements
    assert "aggregates" in elements
    assert len(elements["aggregates"]) == 1
    assert User in elements["aggregates"]

    # Internal entities should not appear
    assert (
        "entities" not in elements
    )  # Since Role is internal, entities key won't exist


def test_public_elements_method():
    """Test the _public_elements method directly"""
    register = _DomainRegistry()

    register.register_element(User, internal=False)
    register.register_element(Role, internal=True)

    # Test public elements for aggregates
    public_aggregates = register._public_elements(DomainObjects.AGGREGATE.value)
    assert len(public_aggregates) == 1
    assert "tests.test_registry.User" in public_aggregates

    # Test public elements for entities (should be empty since Role is internal)
    public_entities = register._public_elements(DomainObjects.ENTITY.value)
    assert len(public_entities) == 0


def test_reset_method():
    """Test that _reset clears all registered elements"""
    register = _DomainRegistry()

    # Register some elements
    register.register_element(User)
    register.register_element(Role)

    # Verify elements are registered
    assert len(register._elements[DomainObjects.AGGREGATE.value]) == 1
    assert len(register._elements[DomainObjects.ENTITY.value]) == 1
    assert len(register._elements_by_name) == 2

    # Reset the registry
    register._reset()

    # Verify all elements are cleared
    assert len(register._elements[DomainObjects.AGGREGATE.value]) == 0
    assert len(register._elements[DomainObjects.ENTITY.value]) == 0
    assert len(register._elements_by_name) == 0

    # Verify structure is still intact
    for element_type in DomainObjects:
        assert element_type.value in register._elements


def test_element_registration_with_same_name():
    """Test that re-registering an element with the same qualified name logs a debug message"""
    register = _DomainRegistry()

    # Register element twice
    register.register_element(User)
    register.register_element(User)  # This should log a debug message but not fail

    # Should still have only one element
    assert len(register._elements[DomainObjects.AGGREGATE.value]) == 1
    assert len(register._elements_by_name["User"]) == 1


def test_domain_record_default_internal_value():
    """Test that DomainRecord has internal=False by default"""
    from protean.domain.registry import DomainRecord

    record = DomainRecord(
        name="User",
        qualname="tests.test_registry.User",
        class_type=DomainObjects.AGGREGATE.value,
        cls=User,
    )

    assert record.internal is False


def test_property_creation_for_all_domain_object_types():
    """Test that properties are created for all domain object types"""
    from protean.domain.registry import properties

    register = _DomainRegistry()

    # Test that all properties from DomainObjects enum are available
    for name, element_type in properties().items():
        assert hasattr(register, name)
        prop_value = getattr(register, name)
        assert isinstance(prop_value, dict)


def test_elements_by_name_tracking():
    """Test that elements are tracked by name for multiple elements with same class name"""
    register = _DomainRegistry()

    class AnotherUser(BaseAggregate):
        name: String(max_length=50)

    # Register first User - this should trigger the 'else' branch
    register.register_element(User)
    assert len(register._elements_by_name["User"]) == 1

    # Change the module to simulate different fully qualified names
    AnotherUser.__module__ = "another.module"

    # Register AnotherUser - this should also trigger the 'else' branch
    register.register_element(AnotherUser)

    # Both should be tracked under their respective class names
    user_elements = register._elements_by_name["User"]
    another_user_elements = register._elements_by_name["AnotherUser"]

    assert len(user_elements) == 1
    assert len(another_user_elements) == 1
    assert user_elements[0].qualname == "tests.test_registry.User"
    # The qualified name will include the local function scope
    assert "another.module" in another_user_elements[0].qualname
    assert "AnotherUser" in another_user_elements[0].qualname


def test_multiple_elements_same_name_different_qualname():
    """Test registering multiple elements with same class name but different modules"""
    register = _DomainRegistry()

    # Create two classes with the same name but different modules
    class TestElement(BaseAggregate):
        field: String()

    class AnotherTestElement(BaseAggregate):
        field: String()

    # Manually set different module names
    TestElement.__name__ = "SameName"
    AnotherTestElement.__name__ = "SameName"
    TestElement.__module__ = "module1"
    AnotherTestElement.__module__ = "module2"

    # Register first element (triggers else branch)
    register.register_element(TestElement)
    assert len(register._elements_by_name["SameName"]) == 1

    # Register second element with same name (triggers if branch)
    register.register_element(AnotherTestElement)
    assert len(register._elements_by_name["SameName"]) == 2

    # Verify both are tracked correctly
    same_name_elements = register._elements_by_name["SameName"]
    assert len(same_name_elements) == 2

    qualnames = [elem.qualname for elem in same_name_elements]
    # The qualnames will include the local function scope, but should contain the module info
    assert any("module1" in qname and "TestElement" in qname for qname in qualnames)
    assert any(
        "module2" in qname and "AnotherTestElement" in qname for qname in qualnames
    )
