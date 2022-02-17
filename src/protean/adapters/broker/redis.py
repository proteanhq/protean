import json

from typing import TYPE_CHECKING, Dict

import redis

from protean.port.broker import BaseBroker
from protean.utils.mixins import Message

if TYPE_CHECKING:
    from protean.domain import Domain


class RedisBroker(BaseBroker):
    """Redis as the Message Broker.

    FIXME: Convert to be a Context Manager, and release connection after use
    """

    def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
        super().__init__(name, domain, conn_info)

        self.redis_instance = redis.Redis.from_url(conn_info["URI"])

    def publish(self, message: Message) -> None:
        # FIXME Accept configuration for database and list name
        self.redis_instance.rpush("messages", json.dumps(message.to_dict()))

    def get_next(self) -> Message:
        bytes_message = self.redis_instance.lpop("messages")
        if bytes_message:
            return Message(json.loads(bytes_message))

        return None

    def _data_reset(self) -> None:
        self.redis_instance.flushall()
