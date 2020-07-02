# Standard Library Imports
from abc import abstractmethod

# Protean
from protean.domain import DomainObjects


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

    def __init__(self, entity_name, meta):
        self.command_cls = getattr(meta, "command_cls", None)
        self.broker = getattr(meta, "broker", None)


class BaseCommandHandler(metaclass=_CommandHandlerMetaclass):
    """Base Subsciber class that should implemented by all Domain CommandHandlers.

    This is also a marker class that is referenced when command handlers are registered
    with the domain
    """

    element_type = DomainObjects.COMMAND_HANDLER

    def __new__(cls, *args, **kwargs):
        if cls is BaseCommandHandler:
            raise TypeError("BaseCommandHandler cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, domain, command_cls):
        self.domain = domain
        self.command_cls = command_cls

    @abstractmethod
    def notify(self, command):
        """Placeholder method for recieving notifications on command"""
        pass
