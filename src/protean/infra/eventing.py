from __future__ import annotations

import asyncio
import functools
import json
import logging

from datetime import datetime
from enum import Enum
from typing import Union

from protean.container import BaseContainer, OptionsMixin
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.repository import BaseRepository
from protean.fields import Auto, DateTime, Dict, Integer, String
from protean.globals import current_domain
from protean.utils import (
    DomainObjects,
    fetch_element_cls_from_registry,
    fully_qualified_name,
)
from protean.utils.importlib import import_from_full_path
from protean.utils.inflection import underscore

logger = logging.getLogger("Server")


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
    name = String(max_length=50)
    owner = String(max_length=50)
    type = String(max_length=15, choices=MessageType)
    payload = Dict()
    version = Integer(default=1)
    created_at = DateTime(default=datetime.utcnow)

    @classmethod
    def to_message(cls, event: BaseEvent) -> dict:
        message = cls(
            name=event.__class__.__name__,
            owner=current_domain.domain_name,
            type=event.element_type.value,
            payload=event.to_dict(),
        )
        return message.to_dict()

    @classmethod
    def from_event_log(cls, event_log: "EventLog") -> dict:
        message = cls(
            **{
                key: getattr(event_log, key)
                for key in [
                    "message_id",
                    "name",
                    "type",
                    "created_at",
                    "owner",
                    "version",
                    "payload",
                ]
            }
        )
        return message.to_dict()


class EventLogStatus(Enum):
    NEW = "NEW"
    PUBLISHED = "PUBLISHED"
    CONSUMED = "CONSUMED"


class EventLog(BaseAggregate):
    message_id = Auto(identifier=True)
    name = String(max_length=50, required=True)
    type = String(max_length=50, required=True)
    owner = String(max_length=50, required=True)
    payload = Dict(required=True)
    version = Integer(required=True, default=1)
    status = String(
        max_length=10, choices=EventLogStatus, default=EventLogStatus.NEW.value
    )
    created_at = DateTime(required=True, default=datetime.utcnow)
    updated_at = DateTime(required=True, default=datetime.utcnow)

    @classmethod
    def from_message(cls, message: Message) -> "EventLog":
        # FIXME Should message be really a dict?
        return cls(
            message_id=message["message_id"],
            name=message["name"],
            type=message["type"],
            owner=message["owner"],
            payload=message["payload"],
            version=message["version"],
            created_at=message["created_at"],
        )

    def touch(self):
        self.updated_at = datetime.utcnow()

    def mark_published(self):
        self.status = EventLogStatus.PUBLISHED.value
        self.touch()

    def mark_consumed(self):
        self.status = EventLogStatus.CONSUMED.value
        self.touch()


class EventLogRepository(BaseRepository):
    class Meta:
        aggregate_cls = EventLog

    def get_most_recent_event_by_type_cls(self, event_cls: BaseEvent) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(name=event_cls.__name__)
            .order_by("-created_at")
            .all()
            .first
        )

    def get_next_to_publish(self) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(status=EventLogStatus.NEW.value)
            .order_by("created_at")
            .all()
            .first
        )

    def get_most_recent_event_by_type(self, event_name: str) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(name=event_name).order_by("-created_at").all().first
        )

    def get_all_events_of_type(self, event_name: str) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(name=event_name).order_by("-created_at").all().items
        )

    def get_all_events_of_type_cls(self, event_cls: BaseEvent) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(name=event_cls.__name__)
            .order_by("-created_at")
            .all()
            .items
        )


class Subscription:
    """Subscriber implementation.
    """

    def __init__(
        self,
        loop: asyncio.BaseEventLoop,
        subscriber_id: str,
        stream_name: str,
        messages_per_tick: int = 10,
        position_update_interval: int = 10,
        origin_stream_name: str = None,
        tick_interval: int = 1,
    ) -> None:
        self.loop = loop

        self.subscriber_id = subscriber_id
        self.stream_name = stream_name
        self.messages_per_tick = messages_per_tick
        self.position_update_interval = position_update_interval
        self.origin_stream_name = origin_stream_name
        self.tick_interval = tick_interval

        self.subscriber_stream_name = f"subscriber_position-${subscriber_id}"

        self.current_position: int = 0
        self.messages_since_last_position_write: int = 0
        self.keep_going: bool = True

    def load_position(self):
        message = current_domain.event_store.read_last_message(
            self.subscriber_stream_name
        )
        if message:
            data = json.loads(message["data"])
            self.current_position = data["position"]
        else:
            self.current_position = 0

    def update_read_position(self, position):
        self.current_position = position
        self.messages_since_last_position_write += 1

        if self.messages_since_last_position_write == self.position_update_interval:
            return self.write_position(position)

        return

    def write_position(self, position):
        print(f"Updating Read Position... {self.subscriber_id} - {position}")

        self.messages_since_last_position_write = 0
        return self.message_store.write(
            self.subscriber_stream_name, "Read", {"position": position}
        )

    def get_next_batch_of_messages(self):
        return current_domain.event_store.read(
            self.stream_name, self.current_position + 1, self.messages_per_tick
        )  # FIXME Implement filtering

    def process_batch(self, messages):
        for message in messages:
            try:
                self.handle_message(message)
                print(
                    f"Position: {message['position']}, Global Position: {message['global_position']}"
                )
                self.update_read_position(message["global_position"])
            except Exception as exc:
                self.log_error(message, exc)

        return len(messages)

    def log_error(self, last_message, error):
        pass

    def handle_message(self, message):
        if self.stream_name.endswith(":command"):
            command_cls = fetch_element_cls_from_registry(
                message["type"], (DomainObjects.COMMAND,)
            )
            command = command_cls(json.loads(message["data"]))
            handler = current_domain.command_handler_for(command_cls)

            if handler:
                return handler()(command)
        else:
            event_cls = fetch_element_cls_from_registry(
                message["type"], (DomainObjects.EVENT,)
            )
            event = event_cls(message["payload"])
            handlers = current_domain.event_handlers_for(event_cls)

            for handler in handlers:
                handler(event)

        return True

    def start(self):
        print(f"Starting --> {self.subscriber_id}...")

        # Load own position from Event store
        self.load_position()
        return self.poll()

    def stop(self):
        self.keep_going = False
        print(f"Stopped {self.subscriber_id}.")

    def poll(self):
        messages_processed = self.tick()

        if self.keep_going:
            self.loop.call_later(self.tick_interval, self.poll)

    def tick(self):
        messages = self.get_next_batch_of_messages()
        if messages:
            return self.process_batch(messages)


class Server:
    def __init__(self, domain: "Domain", test_mode: str = False) -> None:
        self.domain = domain
        self.test_mode = test_mode

        self.loop = asyncio.new_event_loop()

        self.SHUTTING_DOWN = False

    @classmethod
    def from_domain_file(cls, domain: str, domain_file: str, **kwargs) -> Server:
        domain = import_from_full_path(domain=domain, path=domain_file)
        return cls(domain=domain, **kwargs)

    def run(self):
        with self.domain.domain_context():
            try:
                logger.debug("Starting server...")

                # FIXME Control with configuration flag whether to start automatically
                #   When domain is being loaded in another context, for example, as a flask app.
                #
                #   Dev should be able to choose whether to run the app within Flask context,
                #   or as a separate server.
                for _, record in self.domain.registry.command_handlers.items():
                    command_subscription = Subscription(
                        self.loop,
                        record.cls.meta_.stream_name,
                        record.cls.meta_.stream_name,
                    )
                    command_subscription.start()

                for _, record in self.domain.registry.event_sourced_aggregates.items():
                    event_subscription = Subscription(
                        self.loop,
                        record.cls.meta_.stream_name,
                        record.cls.meta_.stream_name,
                    )
                    event_subscription.start()

                if self.test_mode:
                    self.loop.call_soon(self.stop)

                self.loop.run_forever()
            except KeyboardInterrupt:
                # Complete running tasks and cancel safely
                logger.debug("Caught Keyboard interrupt. Cancelling tasks...")
                self.SHUTTING_DOWN = True

                def shutdown_exception_handler(loop, context):
                    if "exception" not in context or not isinstance(
                        context["exception"], asyncio.CancelledError
                    ):
                        loop.default_exception_handler(context)

                self.loop.set_exception_handler(shutdown_exception_handler)

                ##################
                # CANCEL Elegantly
                ##################
                # Handle shutdown gracefully by waiting for all tasks to be cancelled
                # tasks = asyncio.gather(*asyncio.all_tasks(loop=loop), loop=loop, return_exceptions=True)
                # tasks.add_done_callback(lambda t: loop.stop())
                # tasks.cancel()

                # # Keep the event loop running until it is either destroyed or all
                # # tasks have really terminated
                # while not tasks.done() and not loop.is_closed():
                #     loop.run_forever()

                #####################
                # WAIT FOR COMPLETION
                #####################
                pending = asyncio.all_tasks(loop=self.loop)
                self.loop.run_until_complete(asyncio.gather(*pending))
            finally:
                logger.debug("Shutting down...")

                # Signal executor to finish pending futures and free resources
                self.executor.shutdown(wait=True)

                self.loop.stop()
                self.loop.close()

    def stop(self):
        self.SHUTTING_DOWN = True

        # Signal executor to finish pending futures and free resources
        self.executor.shutdown(wait=True)

        self.loop.stop()
        self.loop.close()
