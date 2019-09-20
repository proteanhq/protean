"""Module for Request related Classes"""
# Protean
from protean.domain import DomainObjects
from protean.utils.container import BaseContainer


class BaseRequestObject(BaseContainer):
    """An Abstract Class to define a basic Valid Request Object and its functionality

    Can be initialized from a dictionary.

    Mirroring the REST world, a request object is usually associated with an Entity class, which is
    referenced when necessary for performing lifecycle funtions, like validations, persistence etc.
    """
    element_type = DomainObjects.REQUEST_OBJECT

    is_valid = True

    def __new__(cls, *args, **kwargs):
        if cls is BaseRequestObject:
            raise TypeError("BaseValueObject cannot be instantiated")
        return super().__new__(cls)


class InvalidRequestObject:
    """A utility class to represent an Invalid Request Object

    An object of InvalidRequestObject is created with error information and returned to
    the callee, if data was missing or corrupt in the input provided.
    """
    is_valid = False

    def __init__(self):
        """Initialize a blank Request object with no errors"""
        self.errors = []

    def add_error(self, parameter, message):
        """Utility method to append an error message"""
        self.errors.append({'parameter': parameter, 'message': message})

    @property
    def has_errors(self):
        """Indicates if there are errors"""
        return len(self.errors) > 0
