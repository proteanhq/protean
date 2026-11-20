"""The ``Broker`` service, which wraps one broker adapter, and the ``Brokers``
container, which holds a service for each configured broker."""

import collections.abc
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from typing import TYPE_CHECKING, Any, TypeVar, cast

from protean.core.subscriber import BaseSubscriber
from protean.exceptions import ConfigurationError, NotSupportedError, ValidationError
from protean.infra.registry import brokers as broker_registry
from protean.port.broker import (
    CAPABILITY_PORTS,
    BaseBroker,
    BlockingReadPort,
    BrokerCapabilities,
    BrokerHealth,
    BrokerMessage,
    BrokerPort,
    ConsumerGroupInfo,
    DLQEntry,
    PartitioningPort,
    StreamRetentionPort,
)
from protean.utils import Processing
from protean.utils.consume_idempotency import dispatch_to_subscriber
from protean.utils.globals import current_uow

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)

T = TypeVar("T")

_CONNECTION_ERROR_MARKERS = (
    "connection",
    "timeout",
    "timed out",
    "network",
    "unreachable",
    "refused",
    "reset",
    "broken pipe",
    "socket",
)


def is_connection_error(exc: BaseException) -> bool:
    """Return ``True`` when the message of ``exc`` names a connection problem."""
    error_str = str(exc).lower()
    return any(marker in error_str for marker in _CONNECTION_ERROR_MARKERS)


def _missing_port_members(adapter_cls: type, port: type[object]) -> list[str]:
    """The members `port` adds to `BrokerPort` that `adapter_cls` lacks."""
    added = sorted(
        getattr(port, "__abstractmethods__", frozenset())
        - BrokerPort.__abstractmethods__
    )
    return [member for member in added if not hasattr(adapter_cls, member)]


class Broker:
    """The framework's view of one broker adapter.

    ``domain.brokers[name]`` returns this service. It adds to the adapter:
    recording messages on the current unit of work, one retry after a
    connection error, capability checks, ping timing, the health envelope and
    synchronous dispatch to registered subscribers.

    Raises:
        ConfigurationError: When it is built, if the adapter declares a
            capability flag without subclassing the sub-protocol
            `CAPABILITY_PORTS` maps it to.
    """

    def __init__(self, adapter: BrokerPort) -> None:
        self._adapter = adapter
        self._check_capability_ports()
        self._subscribers: defaultdict[str, set[type[BaseSubscriber]]] = defaultdict(
            set
        )
        self._last_ping_time: float | None = None
        self._last_ping_success: bool | None = None
        self._start_time = time.time()

    @property
    def name(self) -> str:
        return self._adapter.name

    def _check_capability_ports(self) -> None:
        adapter_cls = type(self._adapter)
        for flag, port in CAPABILITY_PORTS.items():
            if flag in self._adapter.capabilities and port not in adapter_cls.__mro__:
                message = (
                    f"Broker '{self._adapter.name}' declares "
                    f"BrokerCapabilities.{flag.name}, but {adapter_cls.__name__} "
                    f"does not subclass {port.__name__}."
                )
                missing = _missing_port_members(adapter_cls, port)
                if missing:
                    message += f" It does not implement: {', '.join(missing)}."
                raise ConfigurationError(message)

    @property
    def domain(self) -> "Domain":
        return self._adapter.domain

    @property
    def capabilities(self) -> BrokerCapabilities:
        """Return the adapter's capability flags."""
        return self._adapter.capabilities

    def has_capability(self, capability: BrokerCapabilities) -> bool:
        """Return ``True`` when the adapter has ``capability``."""
        return capability in self.capabilities

    def has_all_capabilities(self, capabilities: BrokerCapabilities) -> bool:
        """Return ``True`` when the adapter has every flag in ``capabilities``."""
        return (self.capabilities & capabilities) == capabilities

    def has_any_capability(self, capabilities: BrokerCapabilities) -> bool:
        """Return ``True`` when the adapter has at least one flag in ``capabilities``."""
        return bool(self.capabilities & capabilities)

    def _retry_once(self, operation: str, call: Callable[[], T]) -> T:
        """Run ``call``, and run it again once after a connection error.

        Before the second run the adapter reconnects. An error that is not a
        connection error, or a failed reconnect, is raised.
        """
        try:
            return call()
        except Exception as e:
            if not is_connection_error(e):
                raise
            logger.warning(f"Connection error during {operation}: {e}")
            if not self._adapter.reconnect():
                raise
            return call()

    def publish(self, stream: str, message: dict[str, Any]) -> str | None:
        """Publish ``message`` to ``stream``.

        Inside a unit of work, records the message and returns ``None``; the
        unit of work sends it on commit. Outside one, sends it and returns its
        identifier, and in synchronous processing hands it to each subscriber
        registered for ``stream``.

        Raises:
            ValidationError: When ``message`` is empty.
        """
        if not message:
            raise ValidationError({"message": ["Message cannot be empty"]})

        if current_uow:
            logger.debug(f"Recording message {message} in {current_uow} for dispatch")
            current_uow.register_message(stream, message, broker_name=self.name)
            return None

        identifier = self._retry_once(
            "publish", lambda: self._adapter.publish(stream, message)
        )
        self._dispatch_sync(stream, message)
        return identifier

    def _dispatch_sync(self, stream: str, message: dict[str, Any]) -> None:
        """In synchronous processing, hand ``message`` to each subscriber of ``stream``."""
        # ``get`` keeps a publish to a stream with no subscriber from adding a
        # key to the defaultdict.
        subscribers = self._subscribers.get(stream)
        if (
            self.domain.config["message_processing"] == Processing.SYNC.value
            and subscribers
        ):
            for subscriber_cls in subscribers:
                dispatch_to_subscriber(subscriber_cls, message)

    def read(self, stream: str, consumer_group: str, limit: int) -> list[BrokerMessage]:
        """Read up to ``limit`` messages from ``stream`` for ``consumer_group``.

        Returns an empty list when the broker lacks ``CONSUMER_GROUPS``.
        """
        if BrokerCapabilities.CONSUMER_GROUPS not in self.capabilities:
            logger.warning(f"Broker {self.name} does not support consumer groups")
            return []

        return self._retry_once(
            "read", lambda: self._adapter.read(stream, consumer_group, limit)
        )

    def read_blocking(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        limit: int = 1,
    ) -> list[BrokerMessage]:
        """Read up to ``limit`` messages from ``stream`` for one consumer.

        A broker with ``BLOCKING_READ`` waits up to ``timeout_ms`` milliseconds
        for a message. A broker without it reads ``stream`` once with ``read``
        and does not wait. Either read runs again once after a connection
        error.
        """
        if BrokerCapabilities.BLOCKING_READ not in self.capabilities:
            return self._retry_once(
                "read_blocking",
                lambda: self._adapter.read(stream, consumer_group, limit),
            )

        adapter = cast(BlockingReadPort, self._adapter)
        return self._retry_once(
            "read_blocking",
            lambda: adapter.read_blocking(
                stream,
                consumer_group,
                consumer_name,
                timeout_ms=timeout_ms,
                limit=limit,
            ),
        )

    def read_blocking_streams(
        self,
        streams: Sequence[str],
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        limit: int = 1,
    ) -> dict[str, list[BrokerMessage]]:
        """Read several streams for one consumer in one call.

        The result has one key per requested stream, in the order given, with
        an empty list for a stream that returned nothing. An empty ``streams``
        returns ``{}`` without reading. A broker with ``BLOCKING_READ`` waits
        up to ``timeout_ms`` milliseconds in total. A broker without it reads
        each stream once with ``read`` and does not wait. ``limit`` caps the
        messages read from each stream. The read runs again once after a
        connection error.
        """
        if not streams:
            return {}

        if BrokerCapabilities.BLOCKING_READ not in self.capabilities:
            return self._retry_once(
                "read_blocking_streams",
                lambda: self._read_each_stream(streams, consumer_group, limit),
            )

        adapter = cast(BlockingReadPort, self._adapter)
        return self._retry_once(
            "read_blocking_streams",
            lambda: adapter.read_blocking_streams(
                streams,
                consumer_group,
                consumer_name,
                timeout_ms=timeout_ms,
                limit=limit,
            ),
        )

    def _read_each_stream(
        self, streams: Sequence[str], consumer_group: str, limit: int
    ) -> dict[str, list[BrokerMessage]]:
        return {
            stream: self._adapter.read(stream, consumer_group, limit)
            for stream in streams
        }

    def get_next(self, stream: str, consumer_group: str) -> BrokerMessage | None:
        """Return the next message the adapter reads with ``new_messages=True``.

        Skips messages that are pending in the group. Returns ``None`` when
        there is none, or when the broker lacks ``CONSUMER_GROUPS``.
        """
        if BrokerCapabilities.CONSUMER_GROUPS not in self.capabilities:
            logger.warning(f"Broker {self.name} does not support consumer groups")
            return None

        messages = self._retry_once(
            "get_next",
            lambda: self._adapter.read(stream, consumer_group, 1, new_messages=True),
        )
        return messages[0] if messages else None

    def ack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        """Acknowledge a message ``consumer_group`` processed.

        Returns ``False`` when the broker lacks ``ACK_NACK``.
        """
        if BrokerCapabilities.ACK_NACK not in self.capabilities:
            logger.warning(
                f"Broker {self.name} does not support message acknowledgment"
            )
            return False

        return self._retry_once(
            "ack", lambda: self._adapter.ack(stream, message_id, consumer_group)
        )

    def nack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        """Mark a message ``consumer_group`` failed to process for redelivery.

        Returns ``False`` when the broker lacks ``ACK_NACK``.
        """
        if BrokerCapabilities.ACK_NACK not in self.capabilities:
            logger.warning(
                f"Broker {self.name} does not support message negative acknowledgment"
            )
            return False

        return self._retry_once(
            "nack", lambda: self._adapter.nack(stream, message_id, consumer_group)
        )

    def ping(self) -> bool:
        """Return ``True`` when the broker responds, and record how long it took.

        Returns ``False`` when the adapter's ping fails or raises.
        """
        try:
            start_time = time.time()
            result = self._adapter.ping()
            self._last_ping_time = time.time() - start_time
            self._last_ping_success = result
            return result
        except Exception as e:  # noqa: BLE001 - health probe: any adapter fault is "down"
            logger.debug(f"Ping failed for broker {self.name}: {e}")
            self._last_ping_time = None
            self._last_ping_success = False
            return False

    def health(self) -> dict[str, Any]:
        """Return the broker's health in a status envelope.

        The envelope has ``status`` (``healthy``, ``degraded`` or
        ``unhealthy``), ``connected``, ``last_ping_ms``, ``uptime_seconds`` and
        ``details``, the adapter's health record as a dict with its free-form
        details at the top level. A failure while
        gathering it is reported as ``unhealthy`` and not raised.
        """
        try:
            record = self._adapter.health()
            is_connected = self.ping()

            if is_connected and record.healthy:
                status = "healthy"
            elif is_connected:
                status = "degraded"
            else:
                status = "unhealthy"

            return {
                "status": status,
                "connected": is_connected,
                "last_ping_ms": self._last_ping_time * 1000
                if self._last_ping_time is not None
                else None,
                "uptime_seconds": time.time() - self._start_time,
                "details": _health_details(record),
            }
        except Exception as e:  # noqa: BLE001 - health probe: report the fault as unhealthy
            logger.error(f"Error gathering health stats for broker {self.name}: {e}")
            return {
                "status": "unhealthy",
                "connected": False,
                "last_ping_ms": None,
                "uptime_seconds": 0,
                "details": {"error": str(e)},
            }

    def get_connection(self) -> object:
        """Return the adapter's native client, or ``None`` if it has none."""
        return self._adapter.get_connection()

    def clear(self) -> None:
        """Remove every message and consumer group the broker holds."""
        self._adapter.clear()

    def register(self, subscriber_cls: type[BaseSubscriber]) -> None:
        """Register ``subscriber_cls`` for synchronous dispatch on its stream."""
        stream = subscriber_cls.meta_.stream
        self._subscribers[stream].add(subscriber_cls)
        logger.debug(
            f"Broker {self.name}: Registered Subscriber {subscriber_cls.__name__} for stream {stream}"
        )

    # Forwarders for the framework.

    def _create_group(self, stream: str, consumer_group: str) -> None:
        self._adapter.create_group(stream, consumer_group)

    def _consumer_groups(self) -> dict[str, ConsumerGroupInfo]:
        return self._adapter.consumer_groups()

    def _mark_subscription_owned(self, stream: str, consumer_group: str) -> None:
        self._adapter.mark_subscription_owned(stream, consumer_group)

    def _remove_stale_consumers(
        self, stream: str, consumer_group: str, current_consumer: str
    ) -> int:
        return self._adapter.remove_stale_consumers(
            stream, consumer_group, current_consumer
        )

    def _reclaim_idle_pending(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str | None,
        min_idle_ms: int,
    ) -> dict[str, int]:
        return self._adapter.reclaim_idle_pending(
            stream, consumer_group, consumer_name, min_idle_ms
        )

    def _reconnect(self) -> bool:
        return self._adapter.reconnect()

    def _close(self) -> None:
        self._adapter.close()

    # Forwarders for the operations still on ``BaseBroker``.

    def _base_broker(self, operation: str) -> BaseBroker:
        """Return the adapter as a ``BaseBroker``.

        Raises:
            NotSupportedError: When the adapter does not subclass ``BaseBroker``.
        """
        if isinstance(self._adapter, BaseBroker):
            return self._adapter
        raise NotSupportedError(f"Broker {self.name} does not implement `{operation}`.")

    def dlq_list(self, dlq_streams: list[str], limit: int = 100) -> list[DLQEntry]:
        return self._base_broker("dlq_list").dlq_list(dlq_streams, limit)

    def dlq_inspect(self, dlq_stream: str, dlq_id: str) -> DLQEntry | None:
        return self._base_broker("dlq_inspect").dlq_inspect(dlq_stream, dlq_id)

    def dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool:
        return self._base_broker("dlq_replay").dlq_replay(
            dlq_stream, dlq_id, target_stream
        )

    def dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int:
        return self._base_broker("dlq_replay_all").dlq_replay_all(
            dlq_stream, target_stream
        )

    def dlq_purge(self, dlq_stream: str) -> int:
        return self._base_broker("dlq_purge").dlq_purge(dlq_stream)

    def dlq_trim(self, dlq_stream: str, min_id: str) -> int:
        return self._base_broker("dlq_trim").dlq_trim(dlq_stream, min_id)

    def dlq_depth(self, dlq_stream: str) -> int:
        return self._base_broker("dlq_depth").dlq_depth(dlq_stream)

    # Stream retention, for the stream subscription.

    def _trim(self, stream: str) -> int:
        """Remove the entries of ``stream`` every consumer group has acknowledged.

        Returns the number of entries removed, or ``0`` without calling the adapter when the broker lacks
        ``STREAM_RETENTION``.
        """
        if BrokerCapabilities.STREAM_RETENTION not in self.capabilities:
            return 0
        return cast(StreamRetentionPort, self._adapter).trim(stream)

    # Partition-per-key operations (ADR-0028), for the outbox processor, the
    # partitioned stream subscription and the status collector. They skip
    # ``_retry_once``: a fenced read or ack must fail when the lease is lost
    # and not run again, and the partitioned consumer's poll loop already
    # backs off on a broker error.

    def _partitioning(self, operation: str) -> PartitioningPort:
        """Return the adapter as a ``PartitioningPort``.

        Raises:
            NotSupportedError: The broker lacks ``STREAM_PARTITIONING``.
        """
        if BrokerCapabilities.STREAM_PARTITIONING not in self.capabilities:
            raise NotSupportedError(
                f"Broker {self.name} does not advertise STREAM_PARTITIONING, "
                f"required for `{operation}` (ADR-0028)."
            )
        return cast(PartitioningPort, self._adapter)

    def _record_partition(self, category: str, key: str) -> None:
        self._partitioning("record_partition").record_partition(category, key)

    def _partition_keys(self, category: str) -> set[str]:
        return self._partitioning("partition_keys").partition_keys(category)

    def _reap_partition(
        self,
        category: str,
        key: str,
        min_idle_ms: int,
        backfill_suffix: str | None = None,
    ) -> bool:
        return self._partitioning("reap_partition").reap_partition(
            category, key, min_idle_ms, backfill_suffix
        )

    def _acquire_partition_lease(
        self, lease_key: str, generation_key: str, owner_id: str, ttl_ms: int
    ) -> int | None:
        return self._partitioning("acquire_partition_lease").acquire_partition_lease(
            lease_key, generation_key, owner_id, ttl_ms
        )

    def _renew_partition_lease(
        self, lease_key: str, fence_token: str, ttl_ms: int
    ) -> bool:
        return self._partitioning("renew_partition_lease").renew_partition_lease(
            lease_key, fence_token, ttl_ms
        )

    def _release_partition_lease(self, lease_key: str, fence_token: str) -> bool:
        return self._partitioning("release_partition_lease").release_partition_lease(
            lease_key, fence_token
        )

    def _read_partition_fenced(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        lease_key: str,
        fence_token: str,
        limit: int = 1,
        new_messages: bool = True,
    ) -> list[BrokerMessage]:
        return self._partitioning("read_partition_fenced").read_partition_fenced(
            stream,
            consumer_group,
            consumer_name,
            lease_key,
            fence_token,
            limit,
            new_messages,
        )

    def _ack_partition_fenced(
        self,
        stream: str,
        message_id: str,
        consumer_group: str,
        lease_key: str,
        fence_token: str,
    ) -> bool:
        return self._partitioning("ack_partition_fenced").ack_partition_fenced(
            stream, message_id, consumer_group, lease_key, fence_token
        )

    def _reclaim_partition_pending(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        min_idle_ms: int = 0,
        limit: int = 100,
    ) -> list[BrokerMessage]:
        return self._partitioning(
            "reclaim_partition_pending"
        ).reclaim_partition_pending(
            stream, consumer_group, consumer_name, min_idle_ms, limit
        )


def _health_details(record: BrokerHealth) -> dict[str, Any]:
    """Flatten a health record into the ``details`` dict of the envelope.

    An adapter detail named ``healthy``, ``message_counts`` or
    ``consumer_groups`` does not replace the record's own field.
    """
    return {
        **record.details,
        "healthy": record.healthy,
        "message_counts": dict(record.message_counts),
        "consumer_groups": dict(record.consumer_groups),
    }


class Brokers(collections.abc.MutableMapping[str, Broker]):
    """The ``Broker`` service of each broker configured on a domain, by name."""

    def __init__(self, domain: "Domain"):
        self.domain = domain
        self._brokers: dict[str, Broker] = {}

    def __getitem__(self, key: str) -> Broker:
        return self._brokers[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._brokers)

    def __len__(self) -> int:
        return len(self._brokers)

    def __setitem__(self, key: str, value: Broker) -> None:
        self._brokers[key] = value

    def __delitem__(self, key: str) -> None:
        del self._brokers[key]

    def close(self) -> None:
        """Close all broker connections and release resources."""
        if self._brokers:
            for name, broker in self._brokers.items():
                try:
                    broker._close()
                # one broker failing to close must not stop the others; logged
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
        broker_objects = _build_brokers(self, configured_brokers, existing_brokers)
        _close_replaced_brokers(existing_brokers, broker_objects)
        self._brokers = broker_objects
        _register_subscribers(self)

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


def _build_brokers(
    brokers: Brokers,
    configured_brokers: dict[str, Any],
    existing_brokers: dict[str, Broker],
) -> dict[str, Broker]:
    """Return a broker for each configured name, reusing an unchanged one.

    When a construction fails, closes the brokers created in this call and
    re-raises the error.
    """
    broker_objects: dict[str, Broker] = {}
    newly_created: list[Broker] = []

    try:
        for broker_name, config in configured_brokers.items():
            current = existing_brokers.get(broker_name)
            if current is not None and current._adapter.config == config:
                # Configuration unchanged: reuse the live instance so we
                # never disturb a connection the Engine may be actively
                # consuming.
                broker_objects[broker_name] = current
            else:
                broker_cls = broker_registry.get(config["provider"])
                broker = _wrap_adapter(broker_cls(broker_name, brokers.domain, config))
                broker_objects[broker_name] = broker
                newly_created.append(broker)
    except Exception:
        # A construction failure partway through (e.g. an unreachable broker
        # on a re-init tick) must not leak the connections already opened
        # this pass. Roll back only the brokers created here; reused live
        # instances are left untouched.
        for broker in newly_created:
            try:
                broker._close()
            # a close failure must not mask the original error; logged
            except Exception:
                logger.exception("broker.reinit.rollback_close_failed")
        raise

    return broker_objects


def _wrap_adapter(adapter: BrokerPort) -> Broker:
    """Return the ``Broker`` service for ``adapter``.

    When the service rejects the adapter, closes the adapter and re-raises
    the error.
    """
    try:
        return Broker(adapter)
    except ConfigurationError:
        # The adapter never reaches the brokers the caller closes on failure.
        try:
            adapter.close()
        # a close failure must not mask the configuration error; logged
        except Exception:
            logger.exception("broker.init.rejected_adapter_close_failed")
        raise


def _close_replaced_brokers(
    existing_brokers: dict[str, Broker], broker_objects: dict[str, Broker]
) -> None:
    """Close each existing broker that ``broker_objects`` replaced or dropped.

    A broker is replaced when its configuration changed and dropped when it
    is no longer configured. Reused instances are left untouched. A failed
    close is logged, and the other brokers are still closed.
    """
    for broker_name, broker in existing_brokers.items():
        if broker_objects.get(broker_name) is not broker:
            try:
                broker._close()
            # one failed close must not block the new brokers; logged
            except Exception:
                logger.exception("Error closing broker '%s'", broker_name)


def _register_subscribers(brokers: Brokers) -> None:
    """Register each domain subscriber with the broker it names.

    Raises:
        ConfigurationError: A subscriber names a broker that is not configured.
    """
    for subscriber_record in brokers.domain.registry.subscribers.values():
        subscriber_cls = subscriber_record.cls
        broker_name = subscriber_cls.meta_.broker

        if broker_name not in brokers._brokers:
            raise ConfigurationError(f"Broker `{broker_name}` has not been configured.")

        brokers._brokers[broker_name].register(subscriber_cls)
