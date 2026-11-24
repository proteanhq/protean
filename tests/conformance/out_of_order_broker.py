"""An inline broker that declares ``MESSAGE_ORDERING`` and reverses each read.

``tests/conformance/test_plugin.py`` runs the broker suite against it to show
that the suite fails a broker that hands messages out of publish order.
"""

from protean.adapters.broker.inline import InlineBroker
from protean.port.broker import BrokerCapabilities, BrokerMessage


class OutOfOrderBroker(InlineBroker):
    @property
    def capabilities(self) -> BrokerCapabilities:
        return super().capabilities | BrokerCapabilities.MESSAGE_ORDERING

    def read(
        self,
        stream: str,
        consumer_group: str,
        limit: int,
        *,
        new_messages: bool = False,
    ) -> list[BrokerMessage]:
        messages = super().read(
            stream, consumer_group, limit, new_messages=new_messages
        )
        return messages[::-1]
