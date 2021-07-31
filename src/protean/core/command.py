from protean.core.exceptions import InvalidDataError, ValidationError
from protean.utils import DomainObjects, derive_element_class
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

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except ValidationError as exception:
            raise InvalidDataError(exception.messages)


def command_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseCommand)

    element_cls.meta_.broker = (
        kwargs.pop("broker", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.broker)
        or "default"
    )

    return element_cls
