# Standard Library Imports
from collections import defaultdict

# Protean
from protean.core.broker.base import BaseBroker
from protean.globals import current_domain
from protean.utils import fully_qualified_name


class MemoryBroker(BaseBroker):
    def __init__(self, name, domain, conn_info):
        super().__init__(name, domain, conn_info)

        self._subscribers = defaultdict(set)

    def send_message(self, domain_event):
        for subscriber in self._subscribers[fully_qualified_name(domain_event.__class__)]:
            subscriber_object = subscriber(current_domain, domain_event.__class__)
            subscriber_object.notify(domain_event)

    def register(self, domain_event_cls, subscriber_cls):
        self._subscribers[fully_qualified_name(domain_event_cls)].add(subscriber_cls)
