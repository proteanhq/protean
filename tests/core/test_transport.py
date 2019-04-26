"""Tests for Transport Utility Classes"""
from dataclasses import fields

from protean.core.transport import InvalidRequestObject
from protean.core.transport import RequestObject
from protean.core.transport import RequestObjectFactory
from protean.core.transport import ResponseFailure
from protean.core.transport import ResponseSuccess
from protean.core.transport import ResponseSuccessCreated
from protean.core.transport import ResponseSuccessWithNoContent
from protean.core.transport import Status


class DummyValidRequestObject(RequestObject):
    """ Dummy Request object for testing"""
    @classmethod
    def from_dict(cls, entity, adict):
        """Initialize a Request object from a dictionary."""
        pass


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

    def test_name_only(self):
        """Test field definition with name alone"""
        ROClass = RequestObjectFactory.construct('ROClass', ['identifier', 'name'])
        assert hasattr(ROClass, 'name')

        request_object = ROClass.from_dict({'identifier': 12345, 'name': 'John'})
        assert request_object.identifier == 12345
        assert request_object.name == 'John'
        assert request_object.is_valid

    def test_name_and_type(self):
        """Test field definition with name and type"""
        ROClass = RequestObjectFactory.construct('ROClass', [('identifier', int), ('name', str)])

        request_object1 = ROClass.from_dict({'identifier': 12345, 'name': 'John'})
        assert request_object1.identifier == 12345
        assert request_object1.name == 'John'
        assert request_object1.is_valid

        request_object2 = ROClass.from_dict({'identifier': 'abcd', 'name': 'John'})
        assert request_object2.is_valid is False

        request_object2 = ROClass.from_dict({'identifier': 12345, 'name': 56789})
        assert request_object2.is_valid

    def test_name_type_and_params(self):
        """Test field definition with name, type and parameters"""
        ROClass = RequestObjectFactory.construct(
            'ROClass',
            [('identifier', int), ('name', str, {'required': True})])

        declared_fields = fields(ROClass)
        identifier_field = next(item for item in declared_fields if item.name == "identifier")
        assert identifier_field.metadata.get('required', False) is False
        name_field = next(item for item in declared_fields if item.name == "name")
        assert name_field.metadata['required'] is True

    def test_required(self):
        """Test required validation"""
        ROClass = RequestObjectFactory.construct(
            'ROClass',
            [('identifier', int), ('name', str, {'required': True})])

        request_object1 = ROClass.from_dict({'identifier': 12345, 'name': 'John'})
        assert request_object1.identifier == 12345
        assert request_object1.name == 'John'
        assert request_object1.is_valid

        request_object2 = ROClass.from_dict({'identifier': 'abcd'})
        assert request_object2.is_valid is False

    def test_defaulting(self):
        """Test defaulting of values"""
        ROClass = RequestObjectFactory.construct(
            'ROClass',
            [
                ('identifier', int),
                ('name', str, {'required': True}),
                ('age', int, {'default': 35})])

        request_object1 = ROClass.from_dict({'identifier': 12345, 'name': 'John'})
        assert request_object1.is_valid
        assert request_object1.age == 35

        request_object1 = ROClass.from_dict({'identifier': 12345, 'name': 'John', 'age': 10})
        assert request_object1.is_valid
        assert request_object1.age == 10

        request_object1 = ROClass.from_dict({'name': 'John', 'age': 10})
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


class TestResponseObject:
    """Tests for ResponseObject class"""

    def test_init(self):
        """Test that a ResponseObject instance can be initialized"""
        response = ResponseSuccess(Status.SUCCESS)
        assert response is not None
        assert response.code == Status.SUCCESS

    def test_success(self):
        """Test that a ResponseObject is success"""
        response = ResponseSuccess(Status.SUCCESS)
        assert response.success


class TestResponseSuccessCreated:
    """Tests for ResponseSuccessCreated class"""

    def test_init(self):
        """Test that a ResponseSuccessCreated instance can be initialized"""
        response = ResponseSuccessCreated()
        assert response is not None
        assert response.code == Status.SUCCESS_CREATED

    def test_success(self):
        """Test that a ResponseSuccessCreated is success"""
        response = ResponseSuccessCreated()
        assert response.success


class TestResponseSuccessWithNoContent:
    """Tests for ResponseSuccessWithNoContent class"""

    def test_init(self):
        """
        Test that a ResponseSuccessWithNoContent instance can be initialized
        """
        response = ResponseSuccessWithNoContent()
        assert response is not None
        assert response.code == Status.SUCCESS_WITH_NO_CONTENT

    def test_success(self):
        """Test that a ResponseSuccessWithNoContent is success"""
        response = ResponseSuccessWithNoContent()
        assert response.success


class TestResponseFailure:
    """Tests for ResponseFailure class"""

    def test_init(self):
        """Test that a ResponseFailure instance can be initialized"""
        response = ResponseFailure(
            Status.PARAMETERS_ERROR, 'Failed to process')
        assert response is not None
        assert response.code == Status.PARAMETERS_ERROR
        assert response.message == ResponseFailure.exception_message

    def test_success(self):
        """Test that a ResponseFailure is not success"""
        response = ResponseFailure(
            Status.PARAMETERS_ERROR, 'Failed to process')
        assert not response.success

    def test_value(self):
        """Test retrieval of ResponseFailure information"""
        response = ResponseFailure(
            Status.PARAMETERS_ERROR, 'Failed to process')
        assert response is not None

        expected_value = {
            'code': 400,
            'message': 'Something went wrong. Please try later!!'
        }
        assert response.value == expected_value

    def test_util_methods(self):
        """ Test the utility methods for building failure responses"""
        response = ResponseFailure.build_not_found()
        assert response.code == Status.NOT_FOUND

        response = ResponseFailure.build_unprocessable_error()
        assert response.code == Status.UNPROCESSABLE_ENTITY

        response = ResponseFailure.build_parameters_error()
        assert response.code == Status.PARAMETERS_ERROR

        response = ResponseFailure.build_system_error()
        assert response.code == Status.SYSTEM_ERROR

    def test_build_invalid(self):
        """ Test the building of a ResponseFailure from Invalid Request"""
        request_obj = InvalidRequestObject()
        request_obj.add_error('field', 'is required')

        response = ResponseFailure.build_from_invalid_request(request_obj)
        assert response is not None
        assert response.code == Status.UNPROCESSABLE_ENTITY
        expected_value = {
            'code': 422, 'message': {'field': 'is required'}
        }
        assert response.value == expected_value
