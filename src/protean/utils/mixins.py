from __future__ import annotations

import functools
import logging
from collections import defaultdict
from enum import Enum
from typing import Callable, Dict, Union

from protean import fields
from protean.container import BaseContainer, OptionsMixin
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent, Metadata
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ConfigurationError
from protean.globals import current_domain
from protean.utils import fully_qualified_name

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
        if self.metadata.kind == MessageType.EVENT.value:
            element_record = current_domain.registry.events[self.type]
        elif self.metadata.kind == MessageType.COMMAND.value:
            element_record = current_domain.registry.commands[self.type]
        else:
            raise NotImplementedError  # FIXME Handle unknown messages better

        if not element_record:
            raise ConfigurationError(
                f"Element {self.type.split('.')[-1]} is not registered with the domain"
            )

        return element_record.cls(**self.data)

    @classmethod
    def to_message(cls, message_object: Union[BaseEvent, BaseCommand]) -> Message:
        if not message_object.meta_.part_of.meta_.stream_name:
            raise ConfigurationError(
                f"No stream name found for `{message_object.__class__.__name__}`. "
                "Either specify an explicit stream name or associate the event with an aggregate."
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
            stream_name=message_object._metadata.stream_name,
            type=fully_qualified_name(message_object.__class__),
            data=message_object.to_dict(),
            metadata=message_object._metadata,
            expected_version=expected_version,
        )


class handle:
    """Class decorator to mark handler methods in EventHandler and CommandHandler classes."""

    def __init__(self, target_cls: Union[BaseEvent, BaseCommand]) -> None:
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
    def _handle(cls, message: Message) -> None:
        # Use Event-specific handlers if available, or fallback on `$any` if defined
        handlers = cls._handlers[message.type] or cls._handlers["$any"]

        for handler_method in handlers:
            handler_method(cls(), message.to_object())

    @classmethod
    def handle_error(cls, exc: Exception, message: Message) -> None:
        """Default error handler for messages. Can be overridden in subclasses.

        By default, this method logs the error and raises it.
        """
