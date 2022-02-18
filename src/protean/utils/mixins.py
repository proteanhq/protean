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
    kind = fields.String(
        max_length=7, choices=MessageType
    )  # FIXME Make this field mandatory?
    owner = fields.String(max_length=50)
    schema_version = fields.Integer()

    origin_stream_name = fields.String()


class CoreMessage(BaseContainer):
    global_position = fields.Auto(increment=True, identifier=True)
    position = fields.Integer()
    time = fields.DateTime()
    id = fields.Auto()
    stream_name = fields.String(max_length=255)
    type = fields.String()
    data = fields.Dict()
    metadata = fields.ValueObject(MessageMetadata)


class Message(CoreMessage, OptionsMixin):  # FIXME Remove OptionsMixin
    """Base class for Events and Commands.
    It provides concrete implementations for:
    - ID generation
    - Payload construction
    - Serialization and De-serialization
    """

    expected_version = fields.Integer()

    @classmethod
    def derived_metadata(cls, new_message_type: str) -> Dict:
        additional_metadata = {}

        if hasattr(g, "message_in_context"):
            if (
                new_message_type == "COMMAND"
                and g.message_in_context.metadata.kind == "EVENT"
            ):
                additional_metadata[
                    "origin_stream_name"
                ] = g.message_in_context.stream_name

            if (
                new_message_type == "EVENT"
                and g.message_in_context.metadata.kind == "COMMAND"
                and g.message_in_context.metadata.origin_stream_name is not None
            ):
                additional_metadata[
                    "origin_stream_name"
                ] = g.message_in_context.metadata.origin_stream_name
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
                owner=current_domain.domain_name,
                **cls.derived_metadata(MessageType.EVENT.value)
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
    def to_message(cls, object: Union[BaseEvent, BaseCommand]) -> Message:
        if isinstance(object, BaseEvent):
            return cls.to_event_message(object)
        elif isinstance(object, BaseCommand):
            return cls.to_command_message(object)
        else:
            return NotImplementedError()

    @classmethod
    def to_event_message(cls, event: BaseEvent) -> Message:
        # FIXME Should one of `aggregate_cls` or `stream_name` be mandatory?
        if not (event.meta_.aggregate_cls or event.meta_.stream_name):
            raise IncorrectUsageError(
                {
                    "_entity": [
                        f"Event `{event.__class__.__name__}` needs to be associated with an aggregate or a stream"
                    ]
                }
            )

        if has_id_field(event):
            identifier = getattr(event, id_field(event).field_name)
        else:
            identifier = str(uuid4())

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
                owner=current_domain.domain_name,
                **cls.derived_metadata(MessageType.EVENT.value),
            )
            # schema_version=command.meta_.version,  # FIXME Maintain version for event
        )

    @classmethod
    def to_command_message(cls, command: BaseCommand) -> Message:
        # FIXME Should one of `aggregate_cls` or `stream_name` be mandatory?
        if not (command.meta_.aggregate_cls or command.meta_.stream_name):
            raise IncorrectUsageError(
                {
                    "_entity": [
                        f"Command `{command.__class__.__name__}` needs to be associated with an aggregate or a stream"
                    ]
                }
            )

        # Use the value of an identifier field if specified, or generate a new uuid
        if has_id_field(command):
            identifier = getattr(command, id_field(command).field_name)
        else:
            identifier = str(uuid4())

        # Use explicit stream name if provided, or fallback on Aggregate's stream name
        stream_name = (
            command.meta_.stream_name or command.meta_.aggregate_cls.meta_.stream_name
        )

        return cls(
            stream_name=f"{stream_name}:command-{identifier}",
            type=fully_qualified_name(command.__class__),
            data=command.to_dict(),
            metadata=MessageMetadata(
                kind=MessageType.COMMAND.value,
                owner=current_domain.domain_name,
                **cls.derived_metadata(MessageType.COMMAND.value),
            )
            # schema_version=command.meta_.version,  # FIXME Maintain version for command
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
