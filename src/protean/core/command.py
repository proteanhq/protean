# Protean
from protean.core.exceptions import InvalidDataError, ValidationError
from protean.domain import DomainObjects
from protean.utils.container import BaseContainer


class BaseCommand(BaseContainer):
    """The Base class for Protean-Compliant Domain Commands.

    Provides helper methods to custom define attributes, and find attribute names
    during runtime.

    Basic Usage::

        @domain.command
        class UserRegistrationCommand:
            email = String(required=True, max_length=250)
            username = String(required=True, max_length=50)
            password = String(required=True, max_length=255)


    (or)

        class UserRegistrationCommand(BaseCommand):
            email = String(required=True, max_length=250)
            username = String(required=True, max_length=50)
            password = String(required=True, max_length=255)

        domain.register_element(UserRegistrationCommand)
    """

    element_type = DomainObjects.COMMAND

    def __new__(cls, *args, **kwargs):
        if cls is BaseCommand:
            raise TypeError("BaseCommand cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except ValidationError as exception:
            raise InvalidDataError(exception.messages)
