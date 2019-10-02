# Standard Library Imports
from collections import defaultdict

# Protean
from protean.core.broker.base import BaseBroker
from protean.core.domain_event import BaseDomainEvent
from protean.domain import DomainObjects
from protean.globals import current_domain
from protean.utils import fully_qualified_name


class MemoryBroker(BaseBroker):
    def __init__(self, name, domain, conn_info):
        super().__init__(name, domain, conn_info)

        # In case of `MemoryBroker`, the `IS_ASYNC` value will always be `False`.
        conn_info['IS_ASYNC'] = False

        self._subscribers = defaultdict(set)
        self._command_handlers = {}

    def send_message(self, initiator_obj):
        if isinstance(initiator_obj, BaseDomainEvent):
            for subscriber in self._subscribers[fully_qualified_name(initiator_obj.__class__)]:
                subscriber_object = subscriber(current_domain, initiator_obj.__class__)
                subscriber_object.notify(initiator_obj)
        else:
            command_handler = self._command_handlers[fully_qualified_name(initiator_obj.__class__)]
            command_handler.notify(initiator_obj)

    def register(self, initiator_cls, consumer_cls):
        if initiator_cls.element_type == DomainObjects.DOMAIN_EVENT:
            self._subscribers[fully_qualified_name(initiator_cls)].add(consumer_cls)
        else:
            self._command_handlers[fully_qualified_name(initiator_cls)] = consumer_cls
