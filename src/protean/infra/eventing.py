from datetime import datetime
from enum import Enum

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.field.basic import Auto, DateTime, Dict, Identifier, Integer, String
from protean.core.repository import BaseRepository
from protean.globals import current_domain
from protean.utils import generate_identity
from protean.utils.container import BaseContainer


class MessageType(Enum):
    EVENT = "EVENT"
    COMMAND = "COMMAND"


class Message(BaseContainer):
    """Base class for Events and Commands.

    It provides concrete implementations for:
    - ID generation
    - Payload construction
    - Serialization and De-serialization
    """

    message_id = Identifier(identifier=True, default=generate_identity)
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
    version = Integer(required=True)
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
