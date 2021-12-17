from __future__ import annotations

import functools

from collections import defaultdict
from enum import Enum
from typing import Callable, Dict, Type, Union
from uuid import uuid4

from protean.container import BaseContainer, OptionsMixin
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Auto, DateTime, Dict, Integer, String
from protean.globals import current_domain
from protean.reflection import has_id_field, id_field
from protean.utils import fully_qualified_name


class handle:
    """Class decorator to mark handler methods in EventHandler and CommandHandler classes."""

    def __init__(self, target_cls: Union["BaseEvent", "BaseCommand"]) -> None:
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


class MessageType(Enum):
    EVENT = "EVENT"
    COMMAND = "COMMAND"


class Message(BaseContainer, OptionsMixin):  # FIXME Remove OptionsMixin
    """Base class for Events and Commands.
    It provides concrete implementations for:
    - ID generation
    - Payload construction
    - Serialization and De-serialization
    """

    message_id = Auto(identifier=True)
    stream_name = String(max_length=255)
    owner = String(max_length=50)
    type = String()
    kind = String(max_length=15, choices=MessageType)
    data = Dict()
    schema_version = Integer()
    expected_version = Integer()
    time = DateTime()

    @classmethod
    def to_event_message(
        cls, aggregate: "BaseEventSourcedAggregate", event: "BaseEvent"
    ) -> Message:
        identifier = getattr(aggregate, id_field(aggregate).field_name)

        return cls(
            stream_name=f"{aggregate.meta_.stream_name}-{identifier}",
            owner=current_domain.domain_name,
            type=fully_qualified_name(event.__class__),
            kind=event.element_type.value,
            data=event.to_dict(),
            # schema_version=event.meta_.version,  # FIXME Maintain version for event
            # expected_version=aggregate.version  # FIXME Maintain version for Aggregates
        )

    @classmethod
    def to_event(cls, message: Message) -> "BaseEvent":
        event_record = current_domain.registry.events[message.type]
        return event_record.cls(message.data)

    @classmethod
    def to_command_message(
        cls, aggregate_cls: Type["BaseEventSourcedAggregate"], command: "BaseCommand"
    ) -> Message:
        if has_id_field(command):
            identifier = getattr(command, id_field(command).field_name)
        else:
            identifier = str(uuid4())

        return cls(
            stream_name=f"{aggregate_cls.meta_.stream_name}:command-{identifier}",
            owner=current_domain.domain_name,
            type=fully_qualified_name(command.__class__),
            kind=MessageType.COMMAND.value,
            data=command.to_dict(),
            # schema_version=command.meta_.version,  # FIXME Maintain version for command
        )

    @classmethod
    def to_command(cls, message: Message) -> "BaseCommand":
        command_record = current_domain.registry.commands[message.type]
        return command_record.cls(message.data)
