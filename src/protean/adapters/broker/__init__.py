import collections.abc
import logging
from typing import TYPE_CHECKING, Any, Iterator

from protean.exceptions import ConfigurationError
from protean.port.broker import BaseBroker, registry
from protean.utils.globals import current_uow

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class Brokers(collections.abc.MutableMapping[str, BaseBroker]):
    def __init__(self, domain: "Domain"):
        self.domain = domain
        self._brokers: dict[str, BaseBroker] = {}

    def __getitem__(self, key: str) -> BaseBroker:
        return self._brokers[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._brokers) if self._brokers else iter({})

    def __len__(self) -> int:
        return len(self._brokers) if self._brokers else 0

    def __setitem__(self, key: str, value: BaseBroker) -> None:
        self._brokers[key] = value

    def __delitem__(self, key: str) -> None:
        if key in self._brokers:
            del self._brokers[key]

    def _initialize(self) -> None:
        """Read config file and initialize brokers"""
        configured_brokers = self.domain.config["brokers"]
        broker_objects = {}

        logger.debug("Initializing brokers...")
        if configured_brokers and isinstance(configured_brokers, dict):
            if "default" not in configured_brokers:
                raise ConfigurationError("You must define a 'default' broker")

            for broker_name, conn_info in configured_brokers.items():
                provider = conn_info["provider"]
                broker_cls = registry.get(provider)
                broker_objects[broker_name] = broker_cls(
                    broker_name, self.domain, conn_info
                )
        else:
            raise ConfigurationError("Configure at least one broker in the domain")

        self._brokers = broker_objects

        # Initialize subscribers for Brokers
        for _, subscriber_record in self.domain.registry.subscribers.items():
            subscriber_cls = subscriber_record.cls
            broker_name = subscriber_cls.meta_.broker

            if broker_name not in self._brokers:
                raise ConfigurationError(
                    f"Broker `{broker_name}` has not been configured."
                )

            self._brokers[broker_name].register(subscriber_cls)

    def publish(self, stream: str, message: dict[str, Any]) -> None:
        """Publish a message payload to all registered brokers"""
        # Follow a naive strategy and dispatch message directly to message broker
        #   If the operation is enclosed in a Unit of Work, delegate the responsibility
        #   of publishing the message to the UoW
        if current_uow:
            logger.debug(f"Recording message {message} in {current_uow} for dispatch")

            current_uow.register_message(stream, message)
        else:
            logger.debug(
                f"Publishing message {message} to all brokers registered for stream {stream}"
            )

            for _, broker in self._brokers.items():
                broker.publish(stream, message)


# No exports - this module only provides internal domain infrastructure
# Brokers should be accessed via domain.brokers, not imported directly
# Registry should be imported from protean.port.broker
__all__ = []
