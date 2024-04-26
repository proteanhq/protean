from __future__ import annotations

import functools

from collections import defaultdict
from enum import Enum
from typing import Callable, Dict, Union
from uuid import uuid4

from protean import fields
from protean.container import BaseContainer, OptionsMixin
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.event_sourced_aggregate import BaseEventSourcedAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.core.value_object import BaseValueObject
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.globals import current_domain, g
from protean.reflection import has_id_field, id_field
from protean.utils import fully_qualified_name


class MessageType(Enum):
    EVENT = "EVENT"
    COMMAND = "COMMAND"


class MessageMetadata(BaseValueObject):
    # Marks message as a `COMMAND` or an `EVENT`
    kind = fields.String(required=True, max_length=7, choices=MessageType)

    # Name of service that owns the contract of the message
    owner = fields.String(max_length=50)

    # Allows for parsing of different versions, in case of
    #   breaking changes.
    schema_version = fields.Integer()

    # `origin_stream_name` helps keep track of the origin of a message.
    #   A command created by an event is automatically associated with the original stream.
    #   Events raised subsequently by the commands also carry forward the original stream name.
    origin_stream_name = fields.String()


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
    metadata = fields.ValueObject(MessageMetadata)


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
    def derived_metadata(cls, new_message_type: str) -> Dict:
        additional_metadata = {}

        if hasattr(g, "message_in_context"):
            if (
                new_message_type == "COMMAND"
                and g.message_in_context.metadata.kind == "EVENT"
            ):
                additional_metadata["origin_stream_name"] = (
                    g.message_in_context.stream_name
                )

            if (
                new_message_type == "EVENT"
                and g.message_in_context.metadata.kind == "COMMAND"
                and g.message_in_context.metadata.origin_stream_name is not None
            ):
                additional_metadata["origin_stream_name"] = (
                    g.message_in_context.metadata.origin_stream_name
                )
        return additional_metadata

    @classmethod
    def from_dict(cls, message: Dict) -> Message:
        return Message(
            stream_name=message["stream_name"],
            type=message["type"],
            data=message["data"],
            metadata=MessageMetadata(**message["metadata"]),
            position=message["position"],
            global_position=message["global_position"],
            time=message["time"],
            id=message["id"],
        )

    @classmethod
    def to_aggregate_event_message(
        cls, aggregate: BaseEventSourcedAggregate, event: BaseEvent
    ) -> Message:
        identifier = getattr(aggregate, id_field(aggregate).field_name)

        # Use explicit stream name if provided, or fallback on Aggregate's stream name
        stream_name = (
            event.meta_.stream_name or event.meta_.aggregate_cls.meta_.stream_name
        )

        return cls(
            stream_name=f"{stream_name}-{identifier}",
            type=fully_qualified_name(event.__class__),
            data=event.to_dict(),
            metadata=MessageMetadata(
                kind=MessageType.EVENT.value,
                owner=current_domain.name,
                **cls.derived_metadata(MessageType.EVENT.value),
                # schema_version=event.meta_.version,  # FIXME Maintain version for event
            ),
            expected_version=aggregate._version,  # FIXME Maintain version for Aggregates
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
        # FIXME Should one of `aggregate_cls` or `stream_name` be mandatory?
        if not (message_object.meta_.aggregate_cls or message_object.meta_.stream_name):
            raise IncorrectUsageError(
                {
                    "_entity": [
                        f"`{message_object.__class__.__name__}` needs to be associated with an aggregate or a stream"
                    ]
                }
            )

        if has_id_field(message_object):
            identifier = getattr(message_object, id_field(message_object).field_name)
        else:
            identifier = str(uuid4())

        # Use explicit stream name if provided, or fallback on Aggregate's stream name
        stream_name = (
            message_object.meta_.stream_name
            or message_object.meta_.aggregate_cls.meta_.stream_name
        )

        if isinstance(message_object, BaseEvent):
            stream_name = f"{stream_name}-{identifier}"
            kind = MessageType.EVENT.value
        elif isinstance(message_object, BaseCommand):
            stream_name = f"{stream_name}:command-{identifier}"
            kind = MessageType.COMMAND.value
        else:
            raise NotImplementedError  # FIXME Handle unknown messages better

        return cls(
            stream_name=stream_name,
            type=fully_qualified_name(message_object.__class__),
            data=message_object.to_dict(),
            metadata=MessageMetadata(
                kind=kind,
                owner=current_domain.name,
                **cls.derived_metadata(kind),
            ),
            # schema_version=command.meta_.version,  # FIXME Maintain version
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
