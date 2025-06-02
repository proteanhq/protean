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

    def _ensure_group(self, group_name: str) -> None:
        """Bootstrap/create consumer group for Redis PubSub.

        Note: Redis PubSub doesn't have native consumer groups like Redis Streams.
        This implementation creates a Redis key to track the group existence.
        """
        group_key = f"consumer_group:{group_name}"
        if not self.redis_instance.exists(group_key):
            import time

            self.redis_instance.hset(
                group_key,
                mapping={"created_at": str(time.time()), "consumer_count": "0"},
            )

    def _info(self) -> dict:
        """Provide information about consumer groups and consumers for Redis PubSub.

        Returns information about consumer groups stored as Redis keys.
        """
        consumer_groups = {}

        # Get all consumer group keys
        group_keys = self.redis_instance.keys("consumer_group:*")

        for key in group_keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")

            group_name = key.replace("consumer_group:", "")
            group_info = self.redis_instance.hgetall(key)

            # Convert bytes to strings if needed
            if group_info:
                group_info = {
                    k.decode() if isinstance(k, bytes) else k: v.decode()
                    if isinstance(v, bytes)
                    else v
                    for k, v in group_info.items()
                }

                consumer_groups[group_name] = {
                    "consumers": [],  # Redis PubSub doesn't track individual consumers
                    "created_at": float(group_info.get("created_at", 0)),
                    "consumer_count": int(group_info.get("consumer_count", 0)),
                }

        return {"consumer_groups": consumer_groups}

    def _data_reset(self) -> None:
        self.redis_instance.flushall()
