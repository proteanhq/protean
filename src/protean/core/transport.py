"""Module for Data Transport Utility Classes"""
import sys

from abc import ABCMeta
from abc import abstractmethod
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


class InvalidRequestObject:
    """This class defines an Invalid Request Object"""
    is_valid = False

    def __init__(self):
        """Initialize a Request object with no errors"""
        self.errors = []

    def add_error(self, parameter, message):
        """Utility method to append an error message"""
        self.errors.append({'parameter': parameter, 'message': message})

    @property
    def has_errors(self):
        """Indicates if there are errors"""
        return len(self.errors) > 0


class ValidRequestObject(metaclass=ABCMeta):
    """This class defines a Valid Request Object"""
    is_valid = True

    @classmethod
    @abstractmethod
    def from_dict(cls, entity_cls, adict):
        """
        Initialize a Request object from a dictionary.

        It is initialized here as an abstractmethod and
        should be implemented by a concrete class.
        """
        raise NotImplementedError


class ResponseSuccess:
    """This class defines a successful Response Object"""
    success = True

    def __init__(self, code, value=None, message=None):
        """Initialize Successful Response Object"""
        self.code = code
        self.value = value
        self.message = message


class ResponseFailure:
    """This class defines a failure Response Object"""
    success = False
    exception_message = "Something went wrong. Please try later!!"

    def __init__(self, code, message):
        """Initialize a Failure Response Object"""
        self.code = code
        if code in [Status.SYSTEM_ERROR, Status.PARAMETERS_ERROR]:
            self.message = self.exception_message
        else:
            self.message = message

        # Store the original exception if any
        self.exc_type, self.exc, self.trace = sys.exc_info()

    @property
    def value(self):
        """Utility method to return Response Object information"""
        # Set the code to the status value
        if isinstance(self.code, Status):
            code = self.code.value
        else:
            code = self.code
        return {'code': code, 'message': self.message}

    @classmethod
    def build_response(cls, code=Status.SYSTEM_ERROR, message=None):
        """Utility method to build a new Resource Error object"""
        return cls(code, message)

    @classmethod
    def build_from_invalid_request(cls, invalid_request_object):
        """Utility method to build a new Error object from parameters"""
        message = dict([
            (err['parameter'], err['message']) for err in
            invalid_request_object.errors])
        return cls.build_response(Status.UNPROCESSABLE_ENTITY, message)

    @classmethod
    def build_not_found(cls, message=None):
        """Utility method to build a new Resource Error object"""
        return cls(Status.NOT_FOUND, message)

    @classmethod
    def build_system_error(cls, message=None):
        """Utility method to build a new System Error object"""
        return cls(Status.SYSTEM_ERROR, message)

    @classmethod
    def build_parameters_error(cls, message=None):
        """Utility method to build a new Parameter Error object"""
        return cls(Status.PARAMETERS_ERROR, message)

    @classmethod
    def build_unprocessable_error(cls, message=None):
        """Utility method to build a new Parameter Error object"""
        return cls(Status.UNPROCESSABLE_ENTITY, message)


class ResponseSuccessCreated(ResponseSuccess):
    """This class defines a successful created Response Object"""
    status_code = Status.SUCCESS_CREATED

    def __init__(self, value=None, message=None):
        """Initialize Successful created Response Object"""
        super().__init__(self.status_code, value, message)


class ResponseSuccessWithNoContent(ResponseSuccess):
    """This class defines a successful created Response Object"""
    status_code = Status.SUCCESS_WITH_NO_CONTENT

    def __init__(self, value=None, message=None):
        """Initialize Successful created Response Object"""
        super().__init__(self.status_code, value, message)
