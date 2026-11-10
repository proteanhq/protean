# --8<-- [start:full]
# --8<-- [start:broker]
from collections.abc import Mapping
from typing import Any

from protean import Domain
from protean.adapters.broker.inline import InlineBroker
from protean.infra.registry import brokers
from protean.port.broker import (
    BaseBroker,
    BrokerCapabilities,
    BrokerHealth,
    BrokerMessage,
    BrokerPort,
    ConsumerGroupInfo,
    DLQEntry,
)


class DelegatingBroker(BaseBroker, BrokerPort):
    """A broker that hands every operation to an in-memory InlineBroker.

    Replace the delegate calls with calls to your messaging client.
    """

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        super().__init__(name, domain, config)
        # Initialize your broker connection here
        self._delegate = InlineBroker(name, domain, config)

    @property
    def capabilities(self) -> BrokerCapabilities:
        """Declare only the capabilities the broker implements."""
        return self._delegate.capabilities

    # Publishing and reading
    def publish(self, stream: str, message: dict[str, Any]) -> str:
        return self._delegate.publish(stream, message)

    def read(
        self,
        stream: str,
        consumer_group: str,
        limit: int,
        *,
        new_messages: bool = False,
    ) -> list[BrokerMessage]:
        return self._delegate.read(
            stream, consumer_group, limit, new_messages=new_messages
        )

    # Acknowledgment
    def ack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        return self._delegate.ack(stream, message_id, consumer_group)

    def nack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        return self._delegate.nack(stream, message_id, consumer_group)

    # Consumer groups
    def create_group(self, stream: str, consumer_group: str) -> None:
        self._delegate.create_group(stream, consumer_group)

    def consumer_groups(self) -> dict[str, ConsumerGroupInfo]:
        return self._delegate.consumer_groups()

    # Connection and health
    def ping(self) -> bool:
        return self._delegate.ping()

    def health(self) -> BrokerHealth:
        return self._delegate.health()

    def get_connection(self) -> object:
        return self._delegate.get_connection()

    def reconnect(self) -> bool:
        return self._delegate.reconnect()

    def clear(self) -> None:
        self._delegate.clear()

    # Dead letter queue
    def _dlq_list(self, dlq_streams: list[str], limit: int) -> list[DLQEntry]:
        return self._delegate._dlq_list(dlq_streams, limit)

    def _dlq_inspect(self, dlq_stream: str, dlq_id: str) -> DLQEntry | None:
        return self._delegate._dlq_inspect(dlq_stream, dlq_id)

    def _dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool:
        return self._delegate._dlq_replay(dlq_stream, dlq_id, target_stream)

    def _dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int:
        return self._delegate._dlq_replay_all(dlq_stream, target_stream)

    def _dlq_purge(self, dlq_stream: str) -> int:
        return self._delegate._dlq_purge(dlq_stream)


# Make the broker available as `provider = "delegating_inline"`
brokers.register("delegating_inline", f"{__name__}.DelegatingBroker")
# --8<-- [end:broker]

# --8<-- [start:usage]
domain = Domain(name="CustomBroker")
domain.config["brokers"]["default"] = {"provider": "delegating_inline"}
domain.init(traverse=False)

with domain.domain_context():
    broker = domain.brokers["default"]
    broker.publish("orders", {"order_id": "1"})

    identifier, message = broker.get_next("orders", "order-processor")
    acknowledged = broker.ack("orders", identifier, "order-processor")
# --8<-- [end:usage]
# --8<-- [end:full]
