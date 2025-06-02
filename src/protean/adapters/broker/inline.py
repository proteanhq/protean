from collections import defaultdict
from typing import TYPE_CHECKING, Dict

from protean.port.broker import BaseBroker

if TYPE_CHECKING:
    from protean.domain import Domain


class InlineBroker(BaseBroker):
    __broker__ = "inline"

    def __init__(
        self, name: str, domain: "Domain", conn_info: Dict[str, str | bool]
    ) -> None:
        super().__init__(name, domain, conn_info)

        # In case of `InlineBroker`, the `IS_ASYNC` value will always be `False`.
        conn_info["IS_ASYNC"] = False

        # Initialize storage for messages
        self._messages = defaultdict(list)

        # Initialize storage for consumer groups
        # Structure: {group_name: {consumers: set(), created_at: timestamp}}
        self._consumer_groups = {}

    def _publish(self, stream: str, message: dict) -> str:
        """Publish a message dict to the stream"""
        identifier = None
        if "_metadata" in message and "id" in message["_metadata"]:
            identifier = message["_metadata"]["id"]

        self._messages[stream].append(message)

        return identifier

    def _get_next(self, stream: str) -> dict | None:
        """Get next message in stream"""
        if self._messages[stream]:
            return self._messages[stream].pop(0)
        return None

    def read(self, stream: str, no_of_messages: int) -> list[dict]:
        """Read messages from the broker"""
        messages = []
        while no_of_messages > 0 and self._messages[stream]:
            messages.append(self._messages[stream].pop(0))
            no_of_messages -= 1

        return messages

    def _ensure_group(self, group_name: str) -> None:
        """Bootstrap/create consumer group."""
        if group_name not in self._consumer_groups:
            import time

            self._consumer_groups[group_name] = {
                "consumers": set(),
                "created_at": time.time(),
            }

    def _info(self) -> dict:
        """Provide information about consumer groups and consumers."""
        return {
            "consumer_groups": {
                group_name: {
                    "consumers": list(group_info["consumers"]),
                    "created_at": group_info["created_at"],
                    "consumer_count": len(group_info["consumers"]),
                }
                for group_name, group_info in self._consumer_groups.items()
            }
        }

    def _data_reset(self) -> None:
        """Flush all data in broker instance"""
        self._messages.clear()
        self._consumer_groups.clear()
