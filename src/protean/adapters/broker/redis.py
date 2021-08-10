import json

from typing import TYPE_CHECKING, Dict

import redis

from protean.port.broker import BaseBroker

if TYPE_CHECKING:
    from protean.domain import Domain


class RedisBroker(BaseBroker):
    """Redis as the Message Broker.

    FIXME: Convert to be a Context Manager, and release connection after use
    """

    def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
        super().__init__(name, domain, conn_info)

        self.redis_instance = redis.Redis.from_url(conn_info["URI"])

    def publish(self, message: Dict) -> None:
        # FIXME Accept configuration for database and list name
        self.redis_instance.rpush("messages", json.dumps(message))

    def get_next(self) -> Dict:
        bytes_message = self.redis_instance.lpop("messages")
        return json.loads(bytes_message) if bytes_message else None

    def _data_reset(self) -> None:
        self.redis_instance.flushall()
