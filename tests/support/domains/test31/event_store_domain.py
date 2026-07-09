"""Test domain whose event handler uses an event-store subscription.

Used to exercise the multi-worker single-writer guard: ``protean server
--workers N>1`` must refuse to start against this domain (its handler reads
directly from the event store, which has no cluster-wide ownership) unless
``--allow-event-store-multiworker`` is passed.
"""

from protean import Domain
from protean.fields import String
from protean.server.subscription.profiles import SubscriptionType
from protean.utils.mixins import handle

domain = Domain(name="TEST31")


@domain.aggregate
class Order:
    name = String(max_length=100)


@domain.event(part_of=Order)
class OrderPlaced:
    name = String()


@domain.event_handler(part_of=Order, subscription_type=SubscriptionType.EVENT_STORE)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_placed(self, event):
        pass
