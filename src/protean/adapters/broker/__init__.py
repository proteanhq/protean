import collections
import importlib
import logging

from protean.infra.eventing import Message, MessageType

try:
    # Python 3.8+
    collectionsAbc = collections.abc
except AttributeError:  # pragma: no cover
    # Until Python 3.7
    collectionsAbc = collections

from protean.exceptions import ConfigurationError
from protean.globals import current_domain, current_uow
from protean.utils import EventStrategy

logger = logging.getLogger("protean.broker")


class Brokers(collectionsAbc.MutableMapping):
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

        # Initialize command handlers for Brokers
        for _, command_handler_record in self.domain.registry.command_handlers.items():
            command_handler = command_handler_record.cls
            broker_name = command_handler.meta_.broker

            if broker_name not in self._brokers:
                raise ConfigurationError(
                    f"Broker {broker_name} has not been configured."
                )

            self._brokers[broker_name].register(
                command_handler.meta_.command_cls, command_handler
            )

    def publish(self, object):
        """Publish an object to all registered brokers"""
        if self._brokers is None:
            self._initialize()

        message = Message.to_message(object)

        if message["type"] == MessageType.EVENT.value:
            if (
                current_domain.config["EVENT_STRATEGY"]
                == EventStrategy.DB_SUPPORTED.value
            ):
                # Log event into a table and trigger a push asynchronously
                # This will give a chance to recover from errors.
                from protean.infra.eventing import EventLog

                self.domain.repository_for(EventLog).add(EventLog.from_message(message))
            elif current_domain.config["EVENT_STRATEGY"] == EventStrategy.NAIVE.value:
                # Log event into table
                from protean.infra.eventing import EventLog

                self.domain.repository_for(EventLog).add(EventLog.from_message(message))

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
            else:
                raise ConfigurationError(
                    {
                        "domain": [
                            f"Unknown Event Execution config - should be among {[e.value for e in EventStrategy]}"
                        ]
                    }
                )
        elif message["type"] == MessageType.COMMAND.value:
            self._brokers[object.meta_.broker].publish(message)
        else:
            raise ConfigurationError(
                {
                    "domain": [
                        f"Unknown Message Type {object.__name__} - should be an Event or a Command"
                    ]
                }
            )
