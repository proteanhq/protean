from __future__ import annotations

import functools
import logging
from abc import abstractmethod
from collections import defaultdict
from enum import Enum
from typing import Callable, Dict, Type, Union

from protean import fields
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ConfigurationError, InvalidDataError
from protean.utils.container import BaseContainer, OptionsMixin
from protean.utils.eventing import Metadata
from protean.utils.globals import current_domain

logger = logging.getLogger(__name__)


class MessageType(Enum):
    EVENT = "EVENT"
    COMMAND = "COMMAND"
    READ_POSITION = "READ_POSITION"


class MessageRecord(BaseContainer):
    """
    Base Container holding all fields of a message.
    """

    # Primary key. The ordinal position of the message in the entire message store.
    # Global position may have gaps.
    global_position = fields.Auto(increment=True, identifier=True)

    # The ordinal position of the message in its stream.
    # Position is gapless.
    position = fields.Integer()

    # Message creation time
    time = fields.DateTime()

    # Unique ID of the message
    id = fields.Auto()

    # Name of stream to which the message is written
    stream_name = fields.String(max_length=255)

    # The type of the message
    type = fields.String()

    # JSON representation of the message body
    data = fields.Dict()

    # JSON representation of the message metadata
    metadata = fields.ValueObject(Metadata)


class Message(MessageRecord, OptionsMixin):  # FIXME Remove OptionsMixin
    """Generic message class
    It provides concrete implementations for:
    - ID generation
    - Payload construction
    - Serialization and De-serialization
    """

    # Version that the stream is expected to be when the message is written
    expected_version = fields.Integer()

    @classmethod
    def from_dict(cls, message: Dict) -> Message:
        return Message(
            stream_name=message["stream_name"],
            type=message["type"],
            data=message["data"],
            metadata=message["metadata"],
            position=message["position"],
            global_position=message["global_position"],
            time=message["time"],
            id=message["id"],
        )

    def to_object(self) -> Union[BaseEvent, BaseCommand]:
        """Reconstruct the event/command object from the message data."""
        if self.metadata.kind not in [
            MessageType.COMMAND.value,
            MessageType.EVENT.value,
        ]:
            # We are dealing with a malformed or unknown message
            raise InvalidDataError(
                {"kind": ["Message type is not supported for deserialization"]}
            )

        element_cls = current_domain._events_and_commands.get(self.metadata.type, None)

        if element_cls is None:
            raise ConfigurationError(
                f"Message type {self.metadata.type} is not registered with the domain."
            )

        return element_cls(_metadata=self.metadata, **self.data)

    @classmethod
    def to_message(cls, message_object: Union[BaseEvent, BaseCommand]) -> Message:
        if not message_object.meta_.part_of:
            raise ConfigurationError(
                f"`{message_object.__class__.__name__}` is not associated with an aggregate."
            )

        # Set the expected version of the stream
        #   Applies only to events
        expected_version = None
        if message_object._metadata.kind == MessageType.EVENT.value:
            # If this is a Fact Event, don't set an expected version.
            # Otherwise, expect the previous version
            if not message_object.__class__.__name__.endswith("FactEvent"):
                expected_version = message_object._expected_version

        return cls(
            stream_name=message_object._metadata.stream,
            type=message_object.__class__.__type__,
            data=message_object.payload,
            metadata=message_object._metadata,
            expected_version=expected_version,
        )


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
                fn(instance, target_obj)

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
    def _handle(cls, item: Union[Message, BaseCommand, BaseEvent]) -> None:
        """Handle a message or command/event."""

        # Convert Message to object if necessary
        item = item.to_object() if isinstance(item, Message) else item

        # Use specific handlers if available, or fallback on `$any` if defined
        handlers = cls._handlers[item.__class__.__type__] or cls._handlers["$any"]

        for handler_method in handlers:
            handler_method(cls(), item)

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
