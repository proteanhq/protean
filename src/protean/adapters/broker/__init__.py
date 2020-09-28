# Standard Library Imports
import importlib
import logging

from collections.abc import MutableMapping

# Protean
from protean.core.exceptions import ConfigurationError
from protean.globals import current_uow
from protean.utils import DomainObjects

logger = logging.getLogger("protean.broker")


class Brokers(MutableMapping):
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

        self._brokers = broker_objects

        # Initialize subscribers for Brokers
        for _, subscriber_record in self.domain.registry.subscribers.items():
            subscriber = subscriber_record.cls
            broker_name = subscriber.meta_.broker

            if broker_name not in self._brokers:
                raise ConfigurationError(
                    f"Broker {broker_name} has not been configured."
                )

            self._brokers[broker_name].register(
                subscriber.meta_.domain_event, subscriber
            )

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

    def publish(self, domain_event):
        """Publish a domain event to all registered brokers"""
        if self._brokers is None:
            self._initialize()

        # Log event into a table before pushing to brokers. This will give a chance to recover from errors.
        #   There is a pseudo-check to ensure `EventLog` is registered in the domain, to ensure that apps
        #   know about this functionality and opt for it explicitly.
        #   # FIXME Check if Event Log is enabled in config
        # Protean
        from protean.infra.event_log import EventLog

        if (
            "protean.infra.event_log.EventLog"
            in self.domain._domain_registry._elements[
                DomainObjects.AGGREGATE.value
            ]  # FIXME Do not refer to domain
        ):
            event_dao = self.domain.get_dao(EventLog)
            event_dao.create(
                kind=domain_event.__class__.__name__, payload=domain_event.to_dict()
            )

        if current_uow:
            logger.debug(
                f"Recording {domain_event.__class__.__name__} "
                f"with values {domain_event.to_dict()} in {current_uow}"
            )
            current_uow.register_event(domain_event)
        else:
            logger.debug(
                f"Publishing {domain_event.__class__.__name__} with values {domain_event.to_dict()}"
            )
            for broker_name in self._brokers:
                self._brokers[broker_name].send_message(domain_event)

    def publish_command(self, command):
        """Publish a command to registered command handler"""
        if self._brokers is None:
            self._initialize()

        if current_uow:
            logger.debug(
                f"Recording {command.__class__.__name__} "
                f"with values {command.to_dict()} in {current_uow}"
            )
            current_uow.register_command_handler(command)
        else:
            logger.debug(
                f"Publishing {command.__class__.__name__} with values {command.to_dict()}"
            )
            for broker_name in self._brokers:
                self._brokers[broker_name].send_message(command)
