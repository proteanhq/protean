import json
from typing import TYPE_CHECKING, Dict

import redis

from protean.port.broker import BaseBroker

if TYPE_CHECKING:
    from protean.domain import Domain


class RedisPubSubBroker(BaseBroker):
    """Redis as the Message Broker.

    FIXME: Convert to be a Context Manager, and release connection after use
    """

    __broker__ = "redis_pubsub"

    def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
        super().__init__(name, domain, conn_info)

        self.redis_instance = redis.Redis.from_url(conn_info["URI"])

    def _publish(self, channel: str, message: dict) -> str | None:
        # FIXME Accept configuration for database and list name
        identifier = None
        if "_metadata" in message and "id" in message["_metadata"]:
            identifier = message["_metadata"]["id"]

        self.redis_instance.rpush(channel, json.dumps(message))
        return identifier

    def _get_next(self, channel: str) -> dict | None:
        bytes_message = self.redis_instance.lpop(channel)
        if bytes_message:
            return json.loads(bytes_message)

        return None

    def read(self, channel: str, no_of_messages: int) -> list[dict]:
        messages = []
        for _ in range(no_of_messages):
            bytes_message = self.redis_instance.lpop(channel)
            if bytes_message:
                messages.append(json.loads(bytes_message))

        return messages

    def _data_reset(self) -> None:
        self.redis_instance.flushall()
