"""Tests for Transport Utility Classes"""
# Protean
from protean.core.transport import InvalidRequestObject
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
