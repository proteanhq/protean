# Standard Library Imports
from datetime import datetime

# Protean
from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import DateTime, Dict, String
from protean.core.repository.base import BaseRepository
from protean.globals import current_domain


class EventLog(BaseAggregate):
    kind = String(max_length=50, required=True)
    payload = Dict(required=True)
    timestamp = DateTime(required=True, default=datetime.utcnow())


class EventLogRepository(BaseRepository):
    @classmethod
    def get_most_recent_event_by_type(cls, kind: str) -> EventLog:
        event_dao = current_domain.get_dao(EventLog)
        return (
            event_dao.query.filter(kind=kind.__name__)
            .order_by("-timestamp")
            .all()
            .first
        )

    class Meta:
        aggregate_cls = EventLog
