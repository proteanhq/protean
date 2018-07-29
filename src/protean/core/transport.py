"""Module for Data Transport Utility Classes"""

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
    NOT_FOUND = 404
    RESOURCE_CONFLICT = 409
    UNPROCESSABLE_ENTITY = 422
    SYSTEM_ERROR = 500


class InvalidRequestObject:
    """This class defines an Invalid Request Object"""

    def __init__(self):
        """Initialize a Request object with no errors"""
        self.errors = []

    def add_error(self, parameter, message):
        """Utility method to append an error message"""
        self.errors.append({'parameter': parameter, 'message': message})

    def has_errors(self):
        """Utility method to check if there are errors"""
        return len(self.errors) > 0

    def __bool__(self):
        """Override truthiness of these kind of objects to be False"""
        return False


class ValidRequestObject(metaclass=ABCMeta):
    """This class defines a Valid Request Object"""

    @classmethod
    @abstractmethod
    def from_dict(cls, adict):
        """
        Initialize a Request object from a dictionary.

        It is initialized here as an abstractmethod and
        should be implemented by a concrete class.
        """
        raise NotImplementedError

    def __bool__(self):
        return True


class ResponseSuccess:
    """This class defines a successful Response Object"""

    def __init__(self, code, value=None, message=None):
        """Initialize Successful Response Object"""
        self.code = code
        self.value = value
        self.message = message

    def __bool__(self):
        """Override truthiness to True"""
        return True


class ResponseFailure:
    """This class defines a failure Response Object"""
    EXCEPTION_MESSAGE = "Something went wrong. Please try later!!"

    def __init__(self, code, message):
        """Initialize a Failure Response Object"""
        self.code = code
        if code in [500, 400]:
            self.message = self.EXCEPTION_MESSAGE
        else:
            self.message = message

    @property
    def value(self):
        """Utility method to return Response Object information"""
        return {'code': self.code, 'message': self.message}

    def __bool__(self):
        """Override truthiness to False"""
        return False

    @classmethod
    def build_response(cls, code=500, message=None):
        """Utility method to build a new Resource Error object"""
        return cls(code, message)

    @classmethod
    def build_from_invalid_request(cls, invalid_request_object):
        """Utility method to build a new Error object from parameters"""
        message = dict([
            (err['parameter'], err['message']) for err in invalid_request_object.errors
            ])
        return cls.build_response(422, message)
