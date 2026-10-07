# --8<-- [start:full]
# --8<-- [start:broker]
from typing import Any

from protean import Domain
from protean.adapters.broker.inline import InlineBroker
from protean.port.broker import BaseBroker, BrokerCapabilities, DLQEntry, registry


class DelegatingBroker(BaseBroker):
    """A broker that hands every operation to an in-memory InlineBroker.

    Replace the delegate calls with calls to your messaging client.
    """

    def __init__(self, name: str, domain: "Domain", conn_info: dict[str, Any]) -> None:
        super().__init__(name, domain, conn_info)
        # Initialize your broker connection here
        self._delegate = InlineBroker(name, domain, conn_info)

    @property
    def capabilities(self) -> BrokerCapabilities:
        """Declare only the capabilities the broker implements."""
        return self._delegate.capabilities

    # Publishing and reading
    def _publish(self, stream: str, message: dict[str, Any]) -> str:
        return self._delegate._publish(stream, message)

    def _get_next(
        self, stream: str, consumer_group: str
    ) -> tuple[str, dict[str, Any]] | None:
        return self._delegate._get_next(stream, consumer_group)

    def _read(
        self, stream: str, consumer_group: str, no_of_messages: int
    ) -> list[tuple[str, dict[str, Any]]]:
        return self._delegate._read(stream, consumer_group, no_of_messages)

    # Acknowledgment
    def _ack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        return self._delegate._ack(stream, identifier, consumer_group)

    def _nack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        return self._delegate._nack(stream, identifier, consumer_group)

    # Consumer groups
    def _ensure_group(self, group_name: str, stream: str | None = None) -> None:
        self._delegate._ensure_group(group_name, stream)

    # Connection and health
    def _ping(self) -> bool:
        return self._delegate._ping()

    def _health_stats(self) -> dict[str, Any]:
        return self._delegate._health_stats()

    def _ensure_connection(self) -> bool:
        return self._delegate._ensure_connection()

    def _info(self) -> dict[str, Any]:
        return self._delegate._info()

    def _data_reset(self) -> None:
        self._delegate._data_reset()

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
registry.register("delegating_inline", f"{__name__}.DelegatingBroker")
# --8<-- [end:broker]

# --8<-- [start:usage]
domain = Domain(name="CustomBroker")
domain.config["brokers"]["default"] = {"provider": "delegating_inline"}
domain.init(traverse=False)

with domain.domain_context():
    broker = domain.brokers["default"]
    broker.publish("orders", {"order_id": "1"})

    identifier, message = broker.get_next("orders", "order-processor")
    assert message == {"order_id": "1"}
    broker.ack("orders", identifier, "order-processor")
# --8<-- [end:usage]
# --8<-- [end:full]
