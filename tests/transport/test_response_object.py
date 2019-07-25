# Protean
from protean.core.transport import (InvalidRequestObject, ResponseFailure, ResponseSuccess,
                                    ResponseSuccessCreated, ResponseSuccessWithNoContent, Status)


class TestResponseObject:
    """Tests for ResponseObject class"""

    def test_basic_SUCCESS_response_object_construction(self):
        """Test that a ResponseObject instance can be initialized"""
        response = ResponseSuccess(Status.SUCCESS)
        assert response is not None
        assert response.code == Status.SUCCESS

    def test_success_flag_in_SUCCESS_response(self):
        """Test that a ResponseObject is success"""
        response = ResponseSuccess(Status.SUCCESS)
        assert response.is_successful


class TestResponseSuccessCreated:
    """Tests for ResponseSuccessCreated class"""

    def test_basic_SUCCESS_CREATED_response_object_construction(self):
        """Test that a ResponseSuccessCreated instance can be initialized"""
        response = ResponseSuccessCreated()
        assert response is not None
        assert response.code == Status.SUCCESS_CREATED

    def test_success_flag_in_SUCCESS_CREATED_response(self):
        """Test that a ResponseSuccessCreated is success"""
        response = ResponseSuccessCreated()
        assert response.is_successful


class TestResponseSuccessWithNoContent:
    """Tests for ResponseSuccessWithNoContent class"""

    def test_basic_SUCCESS_WITH_NO_CONTENT_response_object_construction(self):
        """
        Test that a ResponseSuccessWithNoContent instance can be initialized
        """
        response = ResponseSuccessWithNoContent()
        assert response is not None
        assert response.code == Status.SUCCESS_WITH_NO_CONTENT

    def test_success_flag_in_SUCCESS_WITH_NO_CONTENT_response(self):
        """Test that a ResponseSuccessWithNoContent is success"""
        response = ResponseSuccessWithNoContent()
        assert response.is_successful


class TestResponseFailure:
    """Tests for ResponseFailure class"""

    def test_basic_failure_response_object_construction(self):
        """Test that a ResponseFailure instance can be initialized"""
        response = ResponseFailure(
            Status.PARAMETERS_ERROR, 'Failed to process')
        assert response is not None
        assert response.code == Status.PARAMETERS_ERROR
        assert response.errors == ResponseFailure.exception_message

    def test_success_flag_in_failed_response(self):
        """Test that a ResponseFailure is not success"""
        response = ResponseFailure(
            Status.PARAMETERS_ERROR, 'Failed to process')
        assert not response.is_successful

    def test_value_in_failed_response(self):
        """Test retrieval of ResponseFailure information"""
        response = ResponseFailure(
            Status.PARAMETERS_ERROR, 'Failed to process')
        assert response is not None

        expected_value = {
            'code': 400,
            'errors': [{'exception': 'Something went wrong. Please try later!!'}]
        }
        assert response.value == expected_value

    def test_utility_methods_that_build_up_failure_responses(self):
        """ Test the utility methods for building failure responses"""
        response = ResponseFailure.build_not_found()
        assert response.code == Status.NOT_FOUND

        response = ResponseFailure.build_unprocessable_error()
        assert response.code == Status.UNPROCESSABLE_ENTITY

        response = ResponseFailure.build_parameters_error()
        assert response.code == Status.PARAMETERS_ERROR

        response = ResponseFailure.build_system_error()
        assert response.code == Status.SYSTEM_ERROR

    def test_values_of_UNPROCESSABLE_ENTITY_response(self):
        """ Test the building of a ResponseFailure from Invalid Request"""
        request_obj = InvalidRequestObject()
        request_obj.add_error('field', 'is required')

        response = ResponseFailure.build_from_invalid_request(request_obj)
        assert response is not None
        assert response.code == Status.UNPROCESSABLE_ENTITY
        expected_value = {
            'code': 422, 'errors': [{'field': 'is required'}]
        }
        assert response.value == expected_value
