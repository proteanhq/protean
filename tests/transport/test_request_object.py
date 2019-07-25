"""Tests for Transport Utility Classes"""
# Standard Library Imports
from dataclasses import fields

# Protean
from protean.core.transport import InvalidRequestObject, RequestObjectFactory
from protean.domain import DomainObjects

# Local/Relative Imports
from .elements import DummyValidRequestObject


class TestRequestObject:

    def test_that_a_request_object_is_registered_with_the_domain_when_declared_with_annotation(self, test_domain):
        @test_domain.request_object
        class ROClass2:
            """ Dummy Request object for testing"""
            @classmethod
            def from_dict(cls, entity, adict):
                """Initialize a Request object from a dictionary."""
                pass

        registered_request_objects = [
            element.name for _, element
            in test_domain.registry._elements[DomainObjects.REQUEST_OBJECT.value].items()]
        assert 'ROClass2' in registered_request_objects


class TestValidRequestObject:
    """Tests for RequestObject class"""

    def test_init(self):
        """Test that a RequestObject instance can be initialized"""

        request_obj = DummyValidRequestObject()
        assert request_obj is not None

    def test_validity(self):
        """Test that RequestObject is valid"""
        request_obj = DummyValidRequestObject()
        assert request_obj.is_valid


class TestRequestObjectFactory:
    """Tests for RequestObjectFactory"""

    def test_init(self):
        """Test construction of a Request Object class"""
        ROClass = RequestObjectFactory.construct('ROClass', ['identifier'])
        assert hasattr(ROClass, 'from_dict')
        assert hasattr(ROClass, 'identifier')

        request_object = ROClass.from_dict({'identifier': 12345})
        assert request_object.identifier == 12345
        assert request_object.is_valid

    def test_that_a_request_object_is_registered_with_the_domain_on_construction(self, test_domain):
        ROClass = RequestObjectFactory.construct('ROClass1', ['identifier'])
        test_domain.register(ROClass)

        registered_request_objects = [
            element.name for _, element
            in test_domain.registry._elements[DomainObjects.REQUEST_OBJECT.value].items()]
        assert 'ROClass1' in registered_request_objects

    def test_construction_of_request_object_with_field_names_only(self):
        """Test field definition with name alone"""
        ROClass3 = RequestObjectFactory.construct('ROClass3', ['identifier', 'name'])
        assert hasattr(ROClass3, 'name')

        request_object = ROClass3.from_dict({'identifier': 12345, 'name': 'John'})
        assert request_object.identifier == 12345
        assert request_object.name == 'John'
        assert request_object.is_valid

    def test_construction_of_request_object_with_field_names_and_types(self):
        """Test field definition with name and type"""
        ROClass4 = RequestObjectFactory.construct('ROClass4', [('identifier', int), ('name', str)])

        request_object1 = ROClass4.from_dict({'identifier': 12345, 'name': 'John'})
        assert request_object1.identifier == 12345
        assert request_object1.name == 'John'
        assert request_object1.is_valid

        request_object2 = ROClass4.from_dict({'identifier': 'abcd', 'name': 'John'})
        assert request_object2.is_valid is False

        request_object2 = ROClass4.from_dict({'identifier': 12345, 'name': 56789})
        assert request_object2.is_valid

    def test_construction_of_request_object_with_field_name_type_and_params(self):
        """Test field definition with name, type and parameters"""
        ROClass5 = RequestObjectFactory.construct(
            'ROClass5',
            [('identifier', int), ('name', str, {'required': True})])

        declared_fields = fields(ROClass5)
        identifier_field = next(item for item in declared_fields if item.name == "identifier")
        assert identifier_field.metadata.get('required', False) is False
        name_field = next(item for item in declared_fields if item.name == "name")
        assert name_field.metadata['required'] is True

    def test_validation_of_required_fields(self):
        """Test required validation"""
        ROClass6 = RequestObjectFactory.construct(
            'ROClass6',
            [('identifier', int), ('name', str, {'required': True})])

        request_object1 = ROClass6.from_dict({'identifier': 12345, 'name': 'John'})
        assert request_object1.identifier == 12345
        assert request_object1.name == 'John'
        assert request_object1.is_valid

        request_object2 = ROClass6.from_dict({'identifier': 'abcd'})
        assert request_object2.is_valid is False

    def test_defaulting_of_values_in_fields(self):
        """Test defaulting of values"""
        ROClass7 = RequestObjectFactory.construct(
            'ROClass7',
            [
                ('identifier', int),
                ('name', str, {'required': True}),
                ('age', int, {'default': 35})])

        request_object1 = ROClass7.from_dict({'identifier': 12345, 'name': 'John'})
        assert request_object1.is_valid
        assert request_object1.age == 35

        request_object1 = ROClass7.from_dict({'identifier': 12345, 'name': 'John', 'age': 10})
        assert request_object1.is_valid
        assert request_object1.age == 10

        request_object1 = ROClass7.from_dict({'name': 'John', 'age': 10})
        assert request_object1.is_valid
        assert request_object1.identifier is None


class TestInvalidRequestObject:
    """Tests for InvalidRequestObject class"""

    def test_init(self):
        """Test that a InvalidRequestObject instance can be initialized"""
        request_obj = InvalidRequestObject()
        assert request_obj is not None

    def test_validity(self):
        """Test that an InvalidRequestObject is not valid"""
        request_obj = InvalidRequestObject()
        assert not request_obj.is_valid

    def test_add_error(self):
        """Test that an error can be added"""
        request_obj = InvalidRequestObject()
        request_obj.add_error('field', 'is required')

        assert request_obj.errors == [
            {'parameter': 'field', 'message': 'is required'}]

    def test_has_errors(self):
        """Test that errors are correctly returned/reported"""
        request_obj = InvalidRequestObject()
        request_obj.add_error('field', 'is required')

        assert request_obj.has_errors
