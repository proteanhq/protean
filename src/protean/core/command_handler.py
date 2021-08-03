from abc import abstractmethod
from typing import Any, Optional
from protean.core.command import BaseCommand
from protean.exceptions import IncorrectUsageError

from protean.utils import DomainObjects, derive_element_class


class _CommandHandlerMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the CommandHandler class later. Specifically, it sets up a `meta_` attribute on
    the CommandHandler to an instance of Meta, either the default of one that is defined in the
    CommandHandler class.

    `meta_` is setup with these attributes:
        * `command`: The command that this command handler is associated with
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize CommandHandler MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of CommandHandler
        # (excluding CommandHandler class itself).
        parents = [b for b in bases if isinstance(b, _CommandHandlerMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop("Meta", None)
        meta = attr_meta or getattr(new_class, "Meta", None)
        setattr(new_class, "meta_", CommandHandlerMeta(name, meta))

        return new_class


class CommandHandlerMeta:
    """ Metadata info for the CommandHandler.

    Options:
    - ``command``: The command that this command handler is associated with
    """

    def __init__(self, entity_name, meta):  # FIXME Remove `entity_name`
        self.command_cls = getattr(meta, "command_cls", None)
        self.broker = getattr(meta, "broker", "default")


class BaseCommandHandler(metaclass=_CommandHandlerMetaclass):
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


def command_handler_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseCommandHandler)

    element_cls.meta_.command_cls = (
        kwargs.pop("command_cls", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.command_cls)
        or None
    )

    element_cls.meta_.broker = (
        kwargs.pop("broker", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.broker)
        or "default"
    )

    if not element_cls.meta_.command_cls:
        raise IncorrectUsageError(
            f"Command Handler `{element_cls.__name__}` needs to be associated with a Command"
        )

    if not element_cls.meta_.broker:
        raise IncorrectUsageError(
            f"Command Handler `{element_cls.__name__}` needs to be associated with a Broker"
        )

    return element_cls
