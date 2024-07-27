from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.mixins import HandlerMixin


class BaseCommandHandler(Element, HandlerMixin, OptionsMixin):
    """Base Command Handler class that should implemented by all Domain CommandHandlers.

    This is also a marker class that is referenced when command handlers are registered
    with the domain
    """

    element_type = DomainObjects.COMMAND_HANDLER

    @classmethod
    def _default_options(cls):
        return [("part_of", None)]

    def __new__(cls, *args, **kwargs):
        if cls is BaseCommandHandler:
            raise NotSupportedError("BaseCommandHandler cannot be instantiated")
        return super().__new__(cls)


def command_handler_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseCommandHandler, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Command Handler `{element_cls.__name__}` needs to be associated with an Aggregate"
        )

    return element_cls
