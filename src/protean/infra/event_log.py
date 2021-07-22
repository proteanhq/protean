from __future__ import annotations

from datetime import datetime

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.field.basic import DateTime, Dict, Integer, String, Auto
from protean.core.message import Message
from protean.core.repository import BaseRepository
from protean.globals import current_domain
from protean.utils.inflection import underscore


class EventLog(BaseAggregate):
    message_id = Auto(identifier=True)
    name = String(max_length=50, required=True)
    type = String(max_length=50, required=True)
    owner = String(max_length=50, required=True)
    payload = Dict(required=True)
    version = Integer(required=True)
    created_at = DateTime(required=True, default=datetime.utcnow)

    @classmethod
    def from_message(cls, message: Message) -> EventLog:
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


class EventLogRepository(BaseRepository):
    @classmethod
    def get_most_recent_event_by_type_cls(cls, event_cls: BaseEvent) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(name=underscore(event_cls.__name__))
            .order_by("-created_at")
            .all()
            .first
        )

    @classmethod
    def get_most_recent_event_by_type(cls, event_name: str) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(name=event_name).order_by("-created_at").all().first
        )

    @classmethod
    def get_all_events_of_type(cls, event_name: str) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(name=event_name).order_by("-created_at").all().items
        )

    @classmethod
    def get_all_events_of_type_cls(cls, event_cls: BaseEvent) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(name=underscore(event_cls.__name__))
            .order_by("-created_at")
            .all()
            .items
        )

    class Meta:
        aggregate_cls = EventLog
