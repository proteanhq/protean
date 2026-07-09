"""Test domain whose event handler uses a stream subscription.

The counterpart to ``event_store_domain.py``: this domain has a real handler
that resolves to a (multi-worker-safe) stream subscription, so ``protean server
--workers N>1`` and ``Supervisor(num_workers=N)`` must start normally against it.
It exercises the guard's negative path with a handler that actually resolves to
``stream``, not merely an empty domain.
"""

from protean import Domain
from protean.fields import String
from protean.server.subscription.profiles import SubscriptionType
from protean.utils.mixins import handle

domain = Domain(name="TEST31_STREAM")


@domain.aggregate
class Order:
    name = String(max_length=100)


@domain.event(part_of=Order)
class OrderPlaced:
    name = String()


@domain.event_handler(part_of=Order, subscription_type=SubscriptionType.STREAM)
class OrderStreamHandler:
    @handle(OrderPlaced)
    def on_placed(self, event):
        pass
