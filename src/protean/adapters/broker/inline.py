from collections import defaultdict
from typing import TYPE_CHECKING, Dict

from protean.port.broker import BaseBroker

if TYPE_CHECKING:
    from protean.domain import Domain


class InlineBroker(BaseBroker):
    def __init__(
        self, name: str, domain: "Domain", conn_info: Dict[str, str | bool]
    ) -> None:
        super().__init__(name, domain, conn_info)

        # In case of `InlineBroker`, the `IS_ASYNC` value will always be `False`.
        conn_info["IS_ASYNC"] = False

        # Initialize storage for messages
        self._messages = defaultdict(list)

    def _publish(self, channel: str, message: dict) -> None:
        """Publish a message dict to the channel"""
        self._messages[channel].append(message)

    def _get_next(self, channel: str) -> dict | None:
        """Get next message in channel"""
        if self._messages[channel]:
            return self._messages[channel].pop(0)
        return None

    def read(self, channel: str, no_of_messages: int) -> list[dict]:
        """Read messages from the broker"""
        messages = []
        while no_of_messages > 0 and self._messages[channel]:
            messages.append(self._messages[channel].pop(0))
            no_of_messages -= 1

        return messages

    def _data_reset(self) -> None:
        """Flush all data in broker instance"""
        self._messages.clear()
