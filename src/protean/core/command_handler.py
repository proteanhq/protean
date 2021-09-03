from abc import abstractmethod
from typing import Any, Optional

from protean.container import Element, OptionsMixin
from protean.core.command import BaseCommand
from protean.utils import DomainObjects, derive_element_class


class BaseCommandHandler(Element, OptionsMixin):
    """Base Command Handler class that should implemented by all Domain CommandHandlers.

    This is also a marker class that is referenced when command handlers are registered
    with the domain
    """

    element_type = DomainObjects.COMMAND_HANDLER

    def __new__(cls, *args, **kwargs):
        if cls is BaseCommandHandler:
            raise TypeError("BaseCommandHandler cannot be instantiated")
        return super().__new__(cls)

    @abstractmethod
    def __call__(self, command: BaseCommand) -> Optional[Any]:
        """Placeholder method for receiving notifications on command"""
        pass

    @classmethod
    def _default_options(cls):
        return [("command_cls", None), ("broker", "default")]


def command_handler_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseCommandHandler, **kwargs)

    return element_cls
