"""Subscription lag monitoring for Protean applications.

Provides a unified view of all subscription statuses without requiring
the Engine to be running.  Works by walking the domain registry to discover
subscriptions, then querying infrastructure (event store, Redis, outbox)
directly for position and lag data.

Usage::

    from protean.server.subscription_status import collect_subscription_statuses

    statuses = collect_subscription_statuses(domain)
    for s in statuses:
        print(f"{s.handler_name}: lag={s.lag}, status={s.status}")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import SubscriptionType
from protean.utils import fqn

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SubscriptionStatus:
    """Status snapshot for a single subscription or outbox processor."""

    name: str
    """Subscription key (matches ``Engine._subscriptions`` keys)."""

    handler_name: str
    """Short class name (e.g. ``"OrderProjector"``)."""

    subscription_type: str
    """One of ``"stream"``, ``"event_store"``, ``"broker"``, or ``"outbox"``."""

    stream_category: str
    """The stream being consumed (or ``"db → broker"`` for outbox)."""

    lag: int | None
    """Messages behind head.  ``None`` when unavailable."""

    pending: int
    """Messages delivered but not yet acknowledged."""

    current_position: str | None
    """Last known processed position."""

    head_position: str | None
    """Current head of the stream."""

    status: str
    """``"ok"`` | ``"lagging"`` | ``"unknown"``."""

    consumer_count: int
    """Number of active consumers (stream subscriptions only)."""

    dlq_depth: int
    """Messages in the dead-letter queue."""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Stream category inference (mirrors Engine._infer_stream_category)
# ---------------------------------------------------------------------------


def _infer_stream_category(handler_cls: type) -> str:
    """Infer the stream category for a handler.

    Mirrors ``Engine._infer_stream_category`` in
    ``src/protean/server/engine.py``.
    """
    meta = getattr(handler_cls, "meta_", None)
    if meta is None:
        raise ValueError(
            f"Handler '{handler_cls.__name__}' has no meta_ attribute. "
            f"Cannot infer stream category."
        )

    # Priority 1: Explicit stream_category on handler
    stream_category = getattr(meta, "stream_category", None)
    if stream_category:
        return stream_category

    # Priority 2: Infer from part_of aggregate
    part_of = getattr(meta, "part_of", None)
    if part_of:
        aggregate_meta = getattr(part_of, "meta_", None)
        if aggregate_meta:
            aggregate_stream = getattr(aggregate_meta, "stream_category", None)
            if aggregate_stream:
                return aggregate_stream

    raise ValueError(
        f"Cannot infer stream category for handler '{handler_cls.__name__}'."
    )


# ---------------------------------------------------------------------------
# EventStore subscription status
# ---------------------------------------------------------------------------


def _collect_event_store_status(
    domain: Domain,
    name: str,
    handler_cls: type,
    stream_category: str,
    *,
    subscriber_name: str | None = None,
) -> SubscriptionStatus:
    """Query the event store for a subscription's position and head."""
    subscriber_name = subscriber_name or fqn(handler_cls)
    position_stream = f"position-{subscriber_name}-{stream_category}"

    try:
        with domain.domain_context():
            store = domain.event_store.store

            # Current position from the position stream
            last_msg = store._read_last_message(position_stream)
            current_position = last_msg["data"]["position"] if last_msg else -1

            # Head of the category stream
            head_position = store.stream_head_position(stream_category)

            # Lag
            if head_position >= 0:
                lag = max(0, head_position - current_position)
            else:
                lag = None

            status = _classify_status(lag)

            return SubscriptionStatus(
                name=name,
                handler_name=handler_cls.__name__,
                subscription_type="event_store",
                stream_category=stream_category,
                lag=lag,
                pending=0,
                current_position=str(current_position),
                head_position=str(head_position),
                status=status,
                consumer_count=0,
                dlq_depth=0,
            )
    except Exception as exc:
        logger.debug(
            "Error collecting event store subscription status for %s: %s",
            name,
            exc,
        )
        return _unknown_status(
            name, handler_cls.__name__, "event_store", stream_category
        )


# ---------------------------------------------------------------------------
# Stream subscription status
# ---------------------------------------------------------------------------


def _collect_stream_status(
    domain: Domain,
    name: str,
    handler_cls: type,
    stream_category: str,
    *,
    consumer_group_name: str | None = None,
) -> SubscriptionStatus:
    """Query Redis for consumer group info and stream length."""
    consumer_group = consumer_group_name or fqn(handler_cls)

    try:
        with domain.domain_context():
            broker = domain.brokers.get("default")
            if not broker or not hasattr(broker, "redis_instance"):
                return _unknown_status(
                    name, handler_cls.__name__, "stream", stream_category
                )

            redis_conn = broker.redis_instance

            # Stream length
            try:
                stream_length = redis_conn.xlen(stream_category)
            except Exception:
                stream_length = 0

            # Consumer group info
            pending = 0
            last_delivered_id: str | None = None
            consumer_count = 0
            lag: int | None = None

            try:
                groups = redis_conn.xinfo_groups(stream_category)
                for g in groups:
                    if not isinstance(g, dict):
                        continue
                    gname = broker._get_field_value(g, "name")
                    if gname == consumer_group:
                        pending = (
                            broker._get_field_value(g, "pending", convert_to_int=True)
                            or 0
                        )
                        last_delivered_id = broker._get_field_value(
                            g, "last-delivered-id"
                        )
                        # Redis 7.0+ native lag field
                        native_lag = broker._get_field_value(
                            g, "lag", convert_to_int=True
                        )
                        if native_lag is not None:
                            lag = native_lag
                        consumer_count = (
                            broker._get_field_value(g, "consumers", convert_to_int=True)
                            or 0
                        )
                        break
            except Exception:
                pass

            # Fallback: count messages after last-delivered-id via xrange
            if lag is None and last_delivered_id is not None:
                try:
                    remaining = redis_conn.xrange(
                        stream_category, min=f"({last_delivered_id}"
                    )
                    lag = len(remaining)
                except Exception:
                    lag = pending  # Lower bound fallback

            # DLQ depth
            dlq_depth = 0
            try:
                dlq_depth = redis_conn.xlen(f"{stream_category}:dlq")
            except Exception:
                pass

            status = _classify_status(lag, pending)

            return SubscriptionStatus(
                name=name,
                handler_name=handler_cls.__name__,
                subscription_type="stream",
                stream_category=stream_category,
                lag=lag,
                pending=pending,
                current_position=str(last_delivered_id) if last_delivered_id else None,
                head_position=str(stream_length),
                status=status,
                consumer_count=consumer_count,
                dlq_depth=dlq_depth,
            )
    except Exception as exc:
        logger.debug(
            "Error collecting stream subscription status for %s: %s", name, exc
        )
        return _unknown_status(name, handler_cls.__name__, "stream", stream_category)


# ---------------------------------------------------------------------------
# Broker subscription status
# ---------------------------------------------------------------------------


def _collect_broker_status(
    domain: Domain,
    name: str,
    handler_cls: type,
    stream_name: str,
    broker_name: str,
) -> SubscriptionStatus:
    """Query broker for consumer group info on an external subscriber stream."""
    consumer_group = fqn(handler_cls)

    try:
        with domain.domain_context():
            broker = domain.brokers.get(broker_name)
            if not broker:
                return _unknown_status(
                    name, handler_cls.__name__, "broker", stream_name
                )

            # Try Redis-style introspection if available
            if hasattr(broker, "redis_instance"):
                redis_conn = broker.redis_instance

                try:
                    stream_length = redis_conn.xlen(stream_name)
                except Exception:
                    stream_length = 0

                pending = 0
                consumer_count = 0
                last_delivered_id: str | None = None
                lag: int | None = None

                try:
                    groups = redis_conn.xinfo_groups(stream_name)
                    for g in groups:
                        if not isinstance(g, dict):
                            continue
                        gname = broker._get_field_value(g, "name")
                        if gname == consumer_group:
                            pending = (
                                broker._get_field_value(
                                    g, "pending", convert_to_int=True
                                )
                                or 0
                            )
                            last_delivered_id = broker._get_field_value(
                                g, "last-delivered-id"
                            )
                            native_lag = broker._get_field_value(
                                g, "lag", convert_to_int=True
                            )
                            if native_lag is not None:
                                lag = native_lag
                            consumer_count = (
                                broker._get_field_value(
                                    g, "consumers", convert_to_int=True
                                )
                                or 0
                            )
                            break
                except Exception:
                    pass

                if lag is None and last_delivered_id is not None:
                    try:
                        remaining = redis_conn.xrange(
                            stream_name, min=f"({last_delivered_id}"
                        )
                        lag = len(remaining)
                    except Exception:
                        lag = pending

                status = _classify_status(lag, pending)

                return SubscriptionStatus(
                    name=name,
                    handler_name=handler_cls.__name__,
                    subscription_type="broker",
                    stream_category=stream_name,
                    lag=lag,
                    pending=pending,
                    current_position=str(last_delivered_id)
                    if last_delivered_id
                    else None,
                    head_position=str(stream_length),
                    status=status,
                    consumer_count=consumer_count,
                    dlq_depth=0,
                )

            # Non-Redis brokers: use info() API
            info = broker.info()
            cg_info = info.get("consumer_groups", {}).get(consumer_group, {})
            pending = cg_info.get("pending", 0)
            consumer_count = cg_info.get("consumer_count", 0)
            status = "ok" if pending == 0 else "lagging"

            return SubscriptionStatus(
                name=name,
                handler_name=handler_cls.__name__,
                subscription_type="broker",
                stream_category=stream_name,
                lag=pending,
                pending=pending,
                current_position=None,
                head_position=None,
                status=status,
                consumer_count=consumer_count,
                dlq_depth=0,
            )
    except Exception as exc:
        logger.debug(
            "Error collecting broker subscription status for %s: %s", name, exc
        )
        return _unknown_status(name, handler_cls.__name__, "broker", stream_name)


# ---------------------------------------------------------------------------
# Outbox processor status
# ---------------------------------------------------------------------------


def _collect_outbox_statuses(domain: Domain) -> list[SubscriptionStatus]:
    """Collect outbox processor statuses for all database providers."""
    statuses: list[SubscriptionStatus] = []

    if not domain.has_outbox:
        return statuses

    outbox_config = domain.config.get("outbox", {})
    broker_provider_name = outbox_config.get("broker", "default")

    for database_provider_name in domain.providers.keys():
        name = f"outbox-processor-{database_provider_name}-to-{broker_provider_name}"
        stream_label = f"{database_provider_name} \u2192 {broker_provider_name}"

        try:
            with domain.domain_context():
                outbox_repo = domain._get_outbox_repo(database_provider_name)
                counts = outbox_repo.count_by_status()

                pending_count = counts.get("pending", 0)
                processing_count = counts.get("processing", 0)
                failed_count = counts.get("failed", 0)
                abandoned_count = counts.get("abandoned", 0)

                lag = pending_count + processing_count
                status = _classify_status(lag)

                statuses.append(
                    SubscriptionStatus(
                        name=name,
                        handler_name="OutboxProcessor",
                        subscription_type="outbox",
                        stream_category=stream_label,
                        lag=lag,
                        pending=pending_count,
                        current_position=None,
                        head_position=None,
                        status=status,
                        consumer_count=0,
                        dlq_depth=failed_count + abandoned_count,
                    )
                )
        except Exception as exc:
            logger.debug(
                "Error collecting outbox processor status for %s: %s", name, exc
            )
            statuses.append(
                _unknown_status(name, "OutboxProcessor", "outbox", stream_label)
            )

    return statuses


# ---------------------------------------------------------------------------
# Public collection function
# ---------------------------------------------------------------------------


def collect_subscription_statuses(domain: Domain) -> list[SubscriptionStatus]:
    """Collect status for all registered subscriptions in a domain.

    Walks the domain registry to discover what subscriptions *would* exist,
    then queries the appropriate backend (event store, Redis, outbox table)
    for lag and position data.

    Does **not** require the Engine to be running.

    Args:
        domain: An initialised Protean domain.

    Returns:
        List of :class:`SubscriptionStatus` for every subscription
        (event handlers, command handlers, projectors, process managers,
        broker subscribers, and outbox processors).
    """
    statuses: list[SubscriptionStatus] = []
    config_resolver = ConfigResolver(domain)

    # 1. Event handlers
    for handler_name, record in domain.registry.event_handlers.items():
        handler_cls = record.cls
        try:
            stream_category = _infer_stream_category(handler_cls)
        except ValueError:
            continue
        config = config_resolver.resolve(handler_cls, stream_category=stream_category)

        if config.subscription_type == SubscriptionType.EVENT_STORE:
            statuses.append(
                _collect_event_store_status(
                    domain, handler_name, handler_cls, stream_category
                )
            )
        else:
            statuses.append(
                _collect_stream_status(
                    domain, handler_name, handler_cls, stream_category
                )
            )

    # 2. Command handlers — grouped by stream category
    handlers_by_stream: dict[str, list[tuple[str, type]]] = defaultdict(list)
    for handler_name, record in domain.registry.command_handlers.items():
        handler_cls = record.cls
        try:
            stream_category = _infer_stream_category(handler_cls)
        except ValueError:
            continue
        handlers_by_stream[stream_category].append((handler_name, handler_cls))

    for stream_category, handlers in handlers_by_stream.items():
        _, first_handler_cls = handlers[0]
        display_name = f"commands:{stream_category}"

        # The Engine's CommandDispatcher sets __module__ and __qualname__
        # so that fqn() returns "protean.server.engine.Commands:{stream}"
        dispatcher_fqn = f"protean.server.engine.Commands:{stream_category}"

        config = config_resolver.resolve(
            first_handler_cls, stream_category=stream_category
        )
        if config.subscription_type == SubscriptionType.EVENT_STORE:
            statuses.append(
                _collect_event_store_status(
                    domain,
                    display_name,
                    first_handler_cls,
                    stream_category,
                    subscriber_name=dispatcher_fqn,
                )
            )
        else:
            statuses.append(
                _collect_stream_status(
                    domain,
                    display_name,
                    first_handler_cls,
                    stream_category,
                    consumer_group_name=dispatcher_fqn,
                )
            )

    # 3. Projectors
    for handler_name, record in domain.registry.projectors.items():
        handler_cls = record.cls
        for stream_category in handler_cls.meta_.stream_categories:
            sub_name = f"{handler_name}-{stream_category}"
            config = config_resolver.resolve(
                handler_cls, stream_category=stream_category
            )
            if config.subscription_type == SubscriptionType.EVENT_STORE:
                statuses.append(
                    _collect_event_store_status(
                        domain, sub_name, handler_cls, stream_category
                    )
                )
            else:
                statuses.append(
                    _collect_stream_status(
                        domain, sub_name, handler_cls, stream_category
                    )
                )

    # 4. Process managers
    for pm_name, record in domain.registry.process_managers.items():
        pm_cls = record.cls
        for stream_category in pm_cls.meta_.stream_categories:
            sub_name = f"{pm_name}-{stream_category}"
            config = config_resolver.resolve(pm_cls, stream_category=stream_category)
            if config.subscription_type == SubscriptionType.EVENT_STORE:
                statuses.append(
                    _collect_event_store_status(
                        domain, sub_name, pm_cls, stream_category
                    )
                )
            else:
                statuses.append(
                    _collect_stream_status(domain, sub_name, pm_cls, stream_category)
                )

    # 5. Broker subscribers
    for subscriber_name, record in domain.registry.subscribers.items():
        subscriber_cls = record.cls
        broker_name = subscriber_cls.meta_.broker
        stream = subscriber_cls.meta_.stream
        statuses.append(
            _collect_broker_status(
                domain, subscriber_name, subscriber_cls, stream, broker_name
            )
        )

    # 6. Outbox processors
    statuses.extend(_collect_outbox_statuses(domain))

    return statuses


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_status(lag: int | None, pending: int = 0) -> str:
    """Classify a subscription's health status."""
    if lag is None:
        return "unknown"
    if lag == 0 and pending == 0:
        return "ok"
    return "lagging"


def _unknown_status(
    name: str,
    handler_name: str,
    subscription_type: str,
    stream_category: str,
) -> SubscriptionStatus:
    """Return a status entry when infrastructure is unreachable."""
    return SubscriptionStatus(
        name=name,
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream_category,
        lag=None,
        pending=0,
        current_position=None,
        head_position=None,
        status="unknown",
        consumer_count=0,
        dlq_depth=0,
    )
