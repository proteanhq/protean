from datetime import datetime
from enum import Enum

from protean.core.event import BaseEvent
from protean.core.field.basic import DateTime, Identifier, Integer, String, Dict
from protean.globals import current_domain
from protean.utils import generate_identity
from protean.utils.container import BaseContainer
from protean.utils.inflection import underscore


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
            name=underscore(event.__class__.__name__),
            owner=current_domain.domain_name,
            type=event.element_type.value,
            payload=event.to_dict(),
        )
        return message.to_dict()
