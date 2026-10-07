# --8<-- [start:declare]
from protean.port.broker import BaseBroker, BrokerCapabilities


class MyBroker(BaseBroker):
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
