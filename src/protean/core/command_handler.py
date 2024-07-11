import inspect

from protean.container import Element, OptionsMixin
from protean.core.command import BaseCommand
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
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
            {
                "_entity": [
                    f"Command Handler `{element_cls.__name__}` needs to be associated with an Aggregate"
                ]
            }
        )

    # Iterate through methods marked as `@handle` and construct a handler map
    if not element_cls._handlers:  # Protect against re-registration
        methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
        for method_name, method in methods:
            if not (
                method_name.startswith("__") and method_name.endswith("__")
            ) and hasattr(method, "_target_cls"):
                # Throw error if target_cls is not a Command
                if not inspect.isclass(method._target_cls) or not issubclass(
                    method._target_cls, BaseCommand
                ):
                    raise IncorrectUsageError(
                        {
                            "_command_handler": [
                                f"Method `{method_name}` in Command Handler `{element_cls.__name__}` "
                                "is not associated with a command"
                            ]
                        }
                    )

                # Throw error if target_cls is not associated with an aggregate
                if not method._target_cls.meta_.part_of:
                    raise IncorrectUsageError(
                        {
                            "_command_handler": [
                                f"Command `{method._target_cls.__name__}` in Command Handler `{element_cls.__name__}` "
                                "is not associated with an aggregate"
                            ]
                        }
                    )

                if method._target_cls.meta_.part_of != element_cls.meta_.part_of:
                    raise IncorrectUsageError(
                        {
                            "_command_handler": [
                                f"Command `{method._target_cls.__name__}` in Command Handler `{element_cls.__name__}` "
                                "is not associated with the same aggregate as the Command Handler"
                            ]
                        }
                    )

                command_type = (
                    method._target_cls.__type__
                    if issubclass(method._target_cls, BaseCommand)
                    else method._target_cls
                )

                # Do not allow multiple handlers per command
                if (
                    command_type in element_cls._handlers
                    and len(element_cls._handlers[command_type]) != 0
                ):
                    raise NotSupportedError(
                        f"Command {method._target_cls.__name__} cannot be handled by multiple handlers"
                    )

                # `_handlers` maps the command to its handler method
                element_cls._handlers[command_type].add(method)

                # Associate Command with the handler's stream
                # Order of preference:
                #   1. Stream name defined in command
                #   2. Stream name derived from aggregate associated with command handler
                method._target_cls.meta_.stream_name = (
                    method._target_cls.meta_.part_of.meta_.stream_name
                    or element_cls.meta_.part_of.meta_.stream_name
                )

    return element_cls
