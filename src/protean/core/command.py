from protean.container import BaseContainer, OptionsMixin
from protean.exceptions import InvalidDataError, ValidationError
from protean.utils import DomainObjects, derive_element_class


class BaseCommand(BaseContainer, OptionsMixin):
    """Base Command class that all commands should inherit from.

    Core functionality associated with commands, like timestamping and authentication, are specified
    as part of the base command class.
    """

    element_type = DomainObjects.COMMAND

    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        try:
            super().__init__(*args, **kwargs)
        except ValidationError as exception:
            raise InvalidDataError(exception.messages)

    @classmethod
    def _default_options(cls):
        return [("broker", "default")]


def command_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseCommand, **kwargs)

    return element_cls
