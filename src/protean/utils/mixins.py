import functools
from collections import defaultdict
from typing import Any, Callable, Type, Union

from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.utils import DomainObjects
from protean.utils.eventing import Message


class handle:
    """Class decorator to mark handler methods in EventHandler and CommandHandler classes."""

    def __init__(self, target_cls: Type[BaseEvent] | Type[BaseCommand]) -> None:
        self._target_cls = target_cls

    def __call__(self, fn: Callable) -> Callable:
        """Marks the method with a special `_target_cls` attribute to be able to
        construct a map of handlers later.

        Args:
            fn (Callable): Handler method

        Returns:
            Callable: Handler method with `_target_cls` attribute
        """

        @functools.wraps(fn)
        def wrapper(instance, target_obj):
            # Wrap function call within a UoW
            with UnitOfWork():
                return fn(instance, target_obj)

        setattr(wrapper, "_target_cls", self._target_cls)
        return wrapper


class HandlerMixin:
    """Mixin to add common handler behavior to Event Handlers and Command Handlers"""

    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        # Associate a `_handlers` map with subclasses.
        # `_handlers` is a dictionary mapping the event/command to handler methods.
        #
        #   It needs to be initialized here because if it
        #   were initialized in __init__, the same collection object
        #   would be made available across all subclasses,
        #   defeating its purpose.
        setattr(subclass, "_handlers", defaultdict(set))

    @classmethod
    def _handle(cls, item: Union[Message, BaseCommand, BaseEvent]) -> Any:
        """Handle a message or command/event.

        Returns:
            Any: Return value from the handler method (only applicable for command handlers)
        """

        # Convert Message to object if necessary
        item = item.to_domain_object() if isinstance(item, Message) else item

        # Use specific handlers if available, or fallback on `$any` if defined
        handlers = cls._handlers[item.__class__.__type__] or cls._handlers["$any"]

        if cls.element_type == DomainObjects.COMMAND_HANDLER:
            # Command handlers only have one handler method per command
            handler_method = next(iter(handlers))
            return handler_method(cls(), item)
        else:
            # Event handlers can have multiple handlers per event
            # Execute all handlers but don't return anything
            for handler_method in handlers:
                handler_method(cls(), item)

        return None

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        """Error handler method called when exceptions occur during message handling.

        This method can be overridden in subclasses to provide custom error handling
        for exceptions that occur during message processing. It allows handlers to
        recover from errors, log additional information, or perform cleanup operations.

        When an exception occurs in a handler method:
        1. The exception is caught in Engine.handle_message or Engine.handle_broker_message
        2. Details are logged with traceback information
        3. This handle_error method is called with the exception and original message
        4. Processing continues with the next message (the engine does not shut down)

        If this method raises an exception itself, that exception is also caught and logged,
        but not propagated further.

        Args:
            exc (Exception): The exception that was raised during message handling
            message (Message): The original message being processed when the exception occurred

        Returns:
            None

        Note:
            - The default implementation does nothing, allowing processing to continue
            - Subclasses can override this method to implement custom error handling strategies
            - This method is called from a try/except block, so exceptions raised here won't crash the engine
        """
