import collections
import importlib
import logging

from protean.exceptions import ConfigurationError

logger = logging.getLogger("protean.broker")


class Brokers(collections.abc.MutableMapping):
    def __init__(self, domain):
        self.domain = domain
        self._brokers = None

    def __getitem__(self, key):
        if self._brokers is None:
            self._initialize()
        return self._brokers[key]

    def __iter__(self):
        if self._brokers is None:
            self._initialize()
        return iter(self._brokers)

    def __len__(self):
        if self._brokers is None:
            self._initialize()
        return len(self._brokers)

    def __setitem__(self, key, value):
        if self._brokers is None:
            self._initialize()
        self._brokers[key] = value

    def __delitem__(self, key):
        if self._brokers is None:
            self._initialize()
        del self._brokers[key]

    def _initialize(self):
        """Read config file and initialize brokers"""
        configured_brokers = self.domain.config["BROKERS"]
        broker_objects = {}

        logger.debug("Initializing brokers...")
        if configured_brokers and isinstance(configured_brokers, dict):
            if "default" not in configured_brokers:
                raise ConfigurationError("You must define a 'default' broker")

            for broker_name, conn_info in configured_brokers.items():
                broker_full_path = conn_info["PROVIDER"]
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
                    f"Broker {broker_name} has not been configured."
                )

            self._brokers[broker_name].register(subscriber.meta_.event, subscriber)
