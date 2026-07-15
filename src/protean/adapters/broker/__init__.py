import collections.abc
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

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

    def close(self) -> None:
        """Close all broker connections and release resources."""
        if self._brokers:
            for name, broker in self._brokers.items():
                try:
                    broker.close()
                except Exception:
                    logger.exception("Error closing broker '%s'", name)
            logger.debug("All brokers closed")

    def _initialize(self) -> None:
        """Read config file and initialize brokers.

        Re-initialization is non-destructive: a broker whose configuration is
        unchanged is reused in place rather than closed and recreated. This
        matters when ``domain.init()`` runs again in a process that is already
        running the Engine (e.g. a scheduler re-initializing the domain on each
        cron tick). Closing a live broker out from under the Engine's consumer
        would null its connection and halt consumption; reusing the existing
        instance keeps the reference the Engine holds alive. Only brokers whose
        configuration changed, or that are no longer configured, are closed.
        """
        configured_brokers = self.domain.config["brokers"]

        if not (configured_brokers and isinstance(configured_brokers, dict)):
            raise ConfigurationError("Configure at least one broker in the domain")
        if "default" not in configured_brokers:
            raise ConfigurationError("You must define a 'default' broker")

        logger.debug("Initializing brokers...")

        existing_brokers = self._brokers
        broker_objects: dict[str, BaseBroker] = {}
        newly_created: list[BaseBroker] = []

        try:
            for broker_name, conn_info in configured_brokers.items():
                current = existing_brokers.get(broker_name)
                if current is not None and current.conn_info == conn_info:
                    # Configuration unchanged — reuse the live instance so we
                    # never disturb a connection the Engine may be actively
                    # consuming. Note the broker enriches ``conn_info`` in place
                    # (e.g. adds ``IS_ASYNC``), and it holds the same dict object
                    # the config does; replacing the config entry with a new dict
                    # is therefore what signals a real change and forces a rebuild.
                    broker_objects[broker_name] = current
                else:
                    provider = conn_info["provider"]
                    broker_cls = registry.get(provider)
                    broker = broker_cls(broker_name, self.domain, conn_info)
                    broker_objects[broker_name] = broker
                    newly_created.append(broker)
        except Exception:
            # A construction failure partway through (e.g. an unreachable broker
            # on a re-init tick) must not leak the connections already opened
            # this pass. Roll back only the brokers created here; reused live
            # instances are left untouched.
            for broker in newly_created:
                try:
                    broker.close()
                except Exception:
                    logger.exception("broker.reinit.rollback_close_failed")
            raise

        # Close brokers that are being replaced (config changed) or dropped
        # (no longer configured). Reused instances are left untouched.
        for broker_name, broker in existing_brokers.items():
            if broker_objects.get(broker_name) is not broker:
                try:
                    broker.close()
                except Exception:
                    logger.exception("Error closing broker '%s'", broker_name)

        self._brokers = broker_objects

        # Initialize subscribers for Brokers
        for subscriber_record in self.domain.registry.subscribers.values():
            subscriber_cls = subscriber_record.cls
            broker_name = subscriber_cls.meta_.broker

            if broker_name not in self._brokers:
                raise ConfigurationError(
                    f"Broker `{broker_name}` has not been configured."
                )

            self._brokers[broker_name].register(subscriber_cls)

    def publish(self, stream: str, message: dict[str, Any]) -> None:
        """Publish a message payload to the default broker.

        If called inside a Unit of Work, the message is deferred until commit.
        """
        if current_uow:
            logger.debug(f"Recording message {message} in {current_uow} for dispatch")

            current_uow.register_message(stream, message)
        else:
            logger.debug(
                f"Publishing message {message} to default broker for stream {stream}"
            )

            self._brokers["default"].publish(stream, message)


# No exports - this module only provides internal domain infrastructure
# Brokers should be accessed via domain.brokers, not imported directly
# Registry should be imported from protean.port.broker
__all__ = []
