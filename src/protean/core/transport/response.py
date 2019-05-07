"""Module for Response related Classes"""
# Standard Library Imports
import sys

from enum import Enum


class Status(Enum):
    """Enum class for Status to Response Code Mapping"""
    SUCCESS = 200
    SUCCESS_CREATED = 201
    SUCCESS_ACCEPTED = 202
    SUCCESS_WITH_NO_CONTENT = 204
    SUCCESS_REFRESH = 205
    PARAMETERS_ERROR = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    RESOURCE_CONFLICT = 409
    UNPROCESSABLE_ENTITY = 422
    SYSTEM_ERROR = 500


class ResponseSuccess:
    """A utility class to represent a successful Response

    Attributes:
        code (integer): HTTP code, for the sake of universal use, to represent
            differnet kinds of success
        value (json): Optional data returned with the response
        message (str): Optional messages returned with the response
    """
    is_successful = True

    def __init__(self, code, value=None, message=None):
        """Initialize Successful Response Object"""
        self.code = code
        self.value = value
        self.message = message


class ResponseFailure:
    """Class to represent a failed Response Object

    Attributes:
        code (integer): HTTP code, among 4xx and 5xx errors
        errors (list): List of key:value format error messages
    """
    is_successful = False
    exception_message = [{"exception": "Something went wrong. Please try later!!"}]

    def __init__(self, code, errors):
        """Initialize a Failure Response Object"""
        self.code = code
        if code in [Status.SYSTEM_ERROR, Status.PARAMETERS_ERROR]:
            self.errors = self.exception_message
        else:
            self.errors = errors

        # Store the original exception if any
        self.exc_type, self.exc, self.trace = sys.exc_info()

    @property
    def value(self):
        """Utility method to retrieve Response Object information"""
        # Set the code to the status value
        if isinstance(self.code, Status):
            code = self.code.value
        else:
            code = self.code
        return {'code': code, 'errors': self.errors}

    @classmethod
    def build_response(cls, code=Status.SYSTEM_ERROR, errors=None):
        """Utility method to build a new Resource Error object.
        Can be used to build all kinds of error messages.
        """
        errors = [errors] if not isinstance(errors, list) else errors
        return cls(code, errors)

    @classmethod
    def build_from_invalid_request(cls, invalid_request_object):
        """Utility method to build a new Error object from parameters.
        Typically used to build HTTP 422 error response."""
        errors = [{err['parameter']: err['message']} for err in invalid_request_object.errors]
        return cls.build_response(Status.UNPROCESSABLE_ENTITY, errors)

    @classmethod
    def build_not_found(cls, errors=None):
        """Utility method to build a HTTP 404 Resource Error response"""
        errors = [errors] if not isinstance(errors, list) else errors
        return cls(Status.NOT_FOUND, errors)

    @classmethod
    def build_system_error(cls, errors=None):
        """Utility method to build a HTTP 500 System Error response"""
        errors = [errors] if not isinstance(errors, list) else errors
        return cls(Status.SYSTEM_ERROR, errors)

    @classmethod
    def build_parameters_error(cls, errors=None):
        """Utility method to build a HTTP 400 Parameter Error response"""
        errors = [errors] if not isinstance(errors, list) else errors
        return cls(Status.PARAMETERS_ERROR, errors)

    @classmethod
    def build_unprocessable_error(cls, errors=None):
        """Utility method to build a HTTP 422 Parameter Error object"""
        errors = [errors] if not isinstance(errors, list) else errors
        return cls(Status.UNPROCESSABLE_ENTITY, errors)


class ResponseSuccessCreated(ResponseSuccess):
    """Helper class to denote a HTTP 201 CREATED response"""
    status_code = Status.SUCCESS_CREATED

    def __init__(self, value=None, errors=None):
        """Initialize Successful created Response Object"""
        super().__init__(self.status_code, value, errors)


class ResponseSuccessWithNoContent(ResponseSuccess):
    """Helper class to denote a HTTP 204 NO CONTENT response"""
    status_code = Status.SUCCESS_WITH_NO_CONTENT

    def __init__(self, value=None, errors=None):
        """Initialize Successful created Response Object"""
        super().__init__(self.status_code, value, errors)
