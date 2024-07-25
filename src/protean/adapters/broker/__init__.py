import collections
import importlib
import logging

from protean.core.event import BaseEvent
from protean.exceptions import ConfigurationError
from protean.utils.globals import current_uow
from protean.utils.mixins import Message

logger = logging.getLogger(__name__)


BROKER_PROVIDERS = {
    "inline": "protean.adapters.InlineBroker",
    "redis": "protean.adapters.broker.redis.RedisBroker",
    "celery": "protean.adapters.broker.celery.CeleryBroker",
}


class Brokers(collections.abc.MutableMapping):
    def __init__(self, domain):
        self.domain = domain
        self._brokers = None

    def __getitem__(self, key):
        return self._brokers[key] if self._brokers else None

    def __iter__(self):
        return iter(self._brokers) if self._brokers else iter({})

    def __len__(self):
        return len(self._brokers) if self._brokers else 0

    def __setitem__(self, key, value):
        if self._brokers is None:
            self._brokers = {}

        self._brokers[key] = value

    def __delitem__(self, key):
        if key in self._brokers:
            del self._brokers[key]

    def _initialize(self):
        """Read config file and initialize brokers"""
        configured_brokers = self.domain.config["brokers"]
        broker_objects = {}

        logger.debug("Initializing brokers...")
        if configured_brokers and isinstance(configured_brokers, dict):
            if "default" not in configured_brokers:
                raise ConfigurationError("You must define a 'default' broker")

            for broker_name, conn_info in configured_brokers.items():
                broker_full_path = BROKER_PROVIDERS[conn_info["provider"]]
                broker_module, broker_class = broker_full_path.rsplit(".", maxsplit=1)

                broker_cls = getattr(
                    importlib.import_module(broker_module), broker_class
                )
                broker_objects[broker_name] = broker_cls(broker_name, self, conn_info)
        else:
            raise ConfigurationError("Configure at least one broker in the domain")

        self._brokers = broker_objects

        # Initialize subscribers for Brokers
        for _, subscriber_record in self.domain.registry.subscribers.items():
            subscriber = subscriber_record.cls
            broker_name = subscriber.meta_.broker

            if broker_name not in self._brokers:
                raise ConfigurationError(
                    f"Broker `{broker_name}` has not been configured."
                )

            self._brokers[broker_name].register(subscriber.meta_.event, subscriber)

    def publish(self, object: BaseEvent) -> None:
        """Publish an object to all registered brokers"""
        message = Message.to_message(object)

        # Follow a naive strategy and dispatch event directly to message broker
        #   If the operation is enclosed in a Unit of Work, delegate the responsibility
        #   of publishing the message to the UoW
        if current_uow:
            logger.debug(
                f"Recording {object.__class__.__name__} "
                f"with values {object.to_dict()} in {current_uow}"
            )
            current_uow.register_message(message)
        else:
            logger.debug(
                f"Publishing {object.__class__.__name__} with values {object.to_dict()}"
            )
            for _, broker in self._brokers.items():
                broker.publish(message)
