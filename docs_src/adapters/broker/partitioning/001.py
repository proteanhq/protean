# --8<-- [start:declare]
from collections.abc import Mapping
from typing import Any

from protean import Domain
from protean.port.broker import BrokerCapabilities, PartitioningPort


class MyBroker(PartitioningPort):
    def __init__(self, name: str, domain: Domain, config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = dict(config)

    @property
    def capabilities(self) -> BrokerCapabilities:
        return (
            BrokerCapabilities.ORDERED_MESSAGING
            | BrokerCapabilities.STREAM_PARTITIONING
        )


# --8<-- [end:declare]


# --8<-- [start:lease_lost]
from protean.port.broker import LeaseLostError

# --8<-- [end:lease_lost]

__all__ = ["LeaseLostError", "MyBroker"]
