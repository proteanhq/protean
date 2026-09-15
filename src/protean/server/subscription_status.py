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

import contextlib
import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast, overload
from uuid import uuid4

from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.event_store_subscription import (
    read_recovery_message,
    reconstruct_unresolved,
    write_recovery_checkpoint_record,
)
from protean.server.subscription.profiles import SubscriptionType
from protean.utils import ensure_utc_aware, fqn
from protean.utils.dlq import failed_positions_stream, recovery_checkpoint_stream
from protean.utils.eventing import MessageType

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class _RedisStyleBroker(Protocol):
    """Structural view of the Redis-backed broker surface used for lag lookups.

    The concrete Redis broker adapters expose ``redis_instance`` (the live
    ``redis.Redis`` client) and the ``_get_field_value`` helper, neither of
    which is part of the ``BaseBroker`` port. Guarded ``hasattr`` checks at the
    call sites narrow a ``BaseBroker`` to this shape. ``redis_instance`` is typed
    ``Any`` because the ``redis`` client is an optional dependency not importable
    at module scope here.
    """

    redis_instance: Any

    @overload
    def _get_field_value(
        self,
        info_dict: dict[Any, Any],
        field_name: str,
        convert_to_int: Literal[False] = ...,
    ) -> str | None: ...

    @overload
    def _get_field_value(
        self,
        info_dict: dict[Any, Any],
        field_name: str,
        convert_to_int: Literal[True],
    ) -> int | None: ...


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

    last_updated: str | None = None
    """ISO timestamp of the last processed position (event-store subscriptions only)."""

    lag_seconds: float | None = None
    """Seconds behind head: ``0.0`` when caught up, time-since-last-update when
    lagging, ``None`` when unknown (event-store subscriptions only)."""

    position_stream: str | None = None
    """The durable checkpoint stream (``position-{subscriber_name}-{category}``)
    for an event-store subscription, ``None`` for other subscription types and
    when the store was unreachable. ``subscriber_name`` is the handler ``fqn`` for
    event handlers, projectors and process managers, and the dispatcher name for
    command handlers. This is the stream ``protean recover --reset-beyond-head``
    writes a fresh position to."""

    recovery_checkpoint_stream: str | None = None
    """The durable recovery-checkpoint stream
    (``recovery-checkpoint-{subscriber_name}-{category}``) for an event-store
    subscription, ``None`` for other subscription types and when the store was
    unreachable. It holds the ``watermark`` and the ``unresolved`` snapshot of
    failed positions the recovery pass rebuilds from on restart. This is the
    stream ``protean recover --reset-beyond-head`` prunes stale entries from."""

    failed_positions_stream: str | None = None
    """The durable failed-positions stream
    (``failed-{subscriber_name}-{category}``) for an event-store subscription,
    ``None`` for other subscription types and when the store was unreachable. It
    holds the ``Failed``/``Resolved``/``Exhausted`` records the recovery pass
    merges after the checkpoint watermark to reconstruct the unresolved set."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Stream category inference (mirrors Engine._infer_stream_category)
# ---------------------------------------------------------------------------


def _infer_stream_category(handler_cls: type[Any]) -> str:
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
    stream_category: str | None = getattr(meta, "stream_category", None)
    if stream_category:
        return stream_category

    # Priority 2: Infer from part_of aggregate
    part_of = getattr(meta, "part_of", None)
    if part_of:
        aggregate_meta = getattr(part_of, "meta_", None)
        if aggregate_meta:
            aggregate_stream: str | None = getattr(
                aggregate_meta, "stream_category", None
            )
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
    handler_cls: type[Any],
    stream_category: str,
    *,
    subscriber_name: str | None = None,
) -> SubscriptionStatus:
    """Query the event store for a subscription's position and head."""
    subscriber_name = subscriber_name or fqn(handler_cls)
    position_stream = f"position-{subscriber_name}-{stream_category}"
    recovery_stream = recovery_checkpoint_stream(subscriber_name, stream_category)
    failed_stream = failed_positions_stream(subscriber_name, stream_category)

    try:
        with domain.domain_context():
            store = domain.event_store.store
            if store is None:
                return _unknown_status(
                    name, handler_cls.__name__, "event_store", stream_category
                )

            # Current position (and when it was last written) from the stream
            last_msg = store._read_last_message(position_stream)
            current_position = last_msg["data"]["position"] if last_msg else -1
            last_updated = _extract_position_time(last_msg)

            # Head of the category stream
            head_position = store.stream_head_position(stream_category)

            # Lag
            if head_position >= 0:
                lag = max(0, head_position - current_position)
            else:
                lag = None

            status = _classify_status(lag)

            lag_seconds = _lag_seconds(lag, last_updated, domain.clock.now())

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
                last_updated=last_updated,
                lag_seconds=lag_seconds,
                position_stream=position_stream,
                recovery_checkpoint_stream=recovery_stream,
                failed_positions_stream=failed_stream,
            )
    except Exception as exc:
        logger.debug(
            "Error collecting event store subscription status for %s: %s",
            name,
            exc,
        )
        unknown = _unknown_status(
            name, handler_cls.__name__, "event_store", stream_category
        )
        # Keep the recovery-tracking stream names (derived from the subscriber
        # name and category, no store read) even when the read-position read
        # failed, so ``protean recover`` can still scan the recovery streams for
        # this subscription instead of skipping it as untracked.
        unknown.recovery_checkpoint_stream = recovery_stream
        unknown.failed_positions_stream = failed_stream
        return unknown


# ---------------------------------------------------------------------------
# Stream subscription status
# ---------------------------------------------------------------------------


def _is_partitioned_category(domain: Domain, stream_category: str) -> bool:
    """Whether events on *stream_category* are physically split per key.

    Mirrors ``SubscriptionFactory._is_partitioned_category``: a category is
    partitioned only when some handler declares ``sequential_by`` on it *and*
    the default broker advertises ``STREAM_PARTITIONING``. Under a
    non-partitioning broker ``sequential_by`` is a no-op and consumers stay on
    the base stream (ADR-0028 decision 8).
    """
    from protean.server.subscription.factory import (  # noqa: PLC0415
        broker_supports_partitioning,
    )

    if stream_category not in getattr(domain, "_partition_keys", {}):
        return False
    return broker_supports_partitioning(domain)


def _collect_partitioned_stream_status(
    domain: Domain,
    name: str,
    handler_cls: type[Any],
    stream_category: str,
    consumer_group: str,
) -> SubscriptionStatus:
    """Sum lag across a partitioned category's per-key streams.

    Under ``sequential_by`` the publisher writes to ``{category}:{key}`` and the
    base stream stays empty, so reading the base stream reports nothing and
    classifies as ``unknown``. That is the framework's own definition of a stuck
    subscription producing no signal, so the partitions are read instead and
    their lag summed. The broker keeps a live index of a category's partition
    keys, which is what makes this cheap enough to do per collection.

    Lag, pending and length add up across partitions. Consumers do not: they are
    counted by name, because one worker appears once in every partition it reads.
    """
    base_broker = domain.brokers.get("default")
    if not base_broker or not hasattr(base_broker, "redis_instance"):
        return _unknown_status(name, handler_cls.__name__, "stream", stream_category)

    broker = cast(_RedisStyleBroker, base_broker)
    redis_conn = broker.redis_instance

    try:
        keys = base_broker._partition_keys(stream_category)
    except Exception as exc:
        logger.debug("Error listing partitions for %s: %s", stream_category, exc)
        return _unknown_status(name, handler_cls.__name__, "stream", stream_category)

    if not keys:
        # No partitions recorded yet: nothing has been published on this
        # category. That is zero lag, not unknown lag.
        return SubscriptionStatus(
            name=name,
            handler_name=handler_cls.__name__,
            subscription_type="stream",
            stream_category=stream_category,
            lag=0,
            pending=0,
            current_position=None,
            head_position="0",
            status="ok",
            consumer_count=0,
            dlq_depth=0,
        )

    total_lag = 0
    total_pending = 0
    total_len = 0
    consumer_names: set[str] = set()
    any_lag_known = False

    for key in sorted(keys):
        partition = f"{stream_category}:{key}"
        with contextlib.suppress(Exception):
            total_len += redis_conn.xlen(partition)
        try:
            groups = redis_conn.xinfo_groups(partition)
        except Exception:
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            if broker._get_field_value(group, "name") != consumer_group:
                continue
            total_pending += (
                broker._get_field_value(group, "pending", convert_to_int=True) or 0
            )
            # Only a real reading counts as knowing the lag. Finding the group
            # is not enough: a broker that reports neither would otherwise
            # contribute 0 from every partition and describe a caught-up
            # subscription whose lag was never read, which is the failure this
            # whole function exists to remove.
            native_lag = broker._get_field_value(group, "lag", convert_to_int=True)
            if native_lag is not None:
                any_lag_known = True
                total_lag += native_lag
            else:
                # No native `lag` (Redis before 7.0). Count what is left after
                # the group's last delivered entry, which is what the
                # non-partitioned path does and what the subscription reference
                # already promises for stream subscriptions. Without this, a
                # partitioned category on Redis 6 reports `unknown` while an
                # identical unpartitioned one reports a number.
                last_delivered_id = broker._get_field_value(group, "last-delivered-id")
                if last_delivered_id is not None:
                    with contextlib.suppress(Exception):
                        remaining = redis_conn.xrange(
                            partition, min=f"({last_delivered_id}"
                        )
                        any_lag_known = True
                        total_lag += len(remaining)
            break

        # Consumers are counted by name, not summed. Each partition is its own
        # stream with its own copy of the consumer group, so a single worker
        # reading five partitions is five consumers by `XINFO GROUPS` and one
        # worker in reality. Summing reports the partition count dressed up as a
        # consumer count. The names are what identify a worker across streams.
        with contextlib.suppress(Exception):
            for consumer in redis_conn.xinfo_consumers(partition, consumer_group):
                if not isinstance(consumer, dict):
                    continue
                consumer_name = broker._get_field_value(consumer, "name")
                if consumer_name is not None:
                    consumer_names.add(consumer_name)

    dlq_depth = 0
    with contextlib.suppress(Exception):
        dlq_depth = redis_conn.xlen(f"{stream_category}:dlq")

    lag = total_lag if any_lag_known else None
    return SubscriptionStatus(
        name=name,
        handler_name=handler_cls.__name__,
        subscription_type="stream",
        stream_category=stream_category,
        lag=lag,
        pending=total_pending,
        current_position=f"{len(keys)} partition(s)",
        head_position=str(total_len),
        status=_classify_status(lag, total_pending),
        consumer_count=len(consumer_names),
        dlq_depth=dlq_depth,
    )


def _collect_stream_status(
    domain: Domain,
    name: str,
    handler_cls: type[Any],
    stream_category: str,
    *,
    consumer_group_name: str | None = None,
) -> SubscriptionStatus:
    """Query Redis for consumer group info and stream length."""
    consumer_group = consumer_group_name or fqn(handler_cls)

    try:
        with domain.domain_context():
            # A `sequential_by` category is published to `{category}:{key}`
            # streams, so the base stream this function reads is empty and would
            # report `unknown`. Read the partitions instead.
            if _is_partitioned_category(domain, stream_category):
                return _collect_partitioned_stream_status(
                    domain, name, handler_cls, stream_category, consumer_group
                )

            base_broker = domain.brokers.get("default")
            if not base_broker or not hasattr(base_broker, "redis_instance"):
                return _unknown_status(
                    name, handler_cls.__name__, "stream", stream_category
                )

            broker = cast(_RedisStyleBroker, base_broker)
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
                    # Leave lag unknown rather than falling back to `pending`.
                    # With nothing pending that fallback yields lag=0, which
                    # classifies as "ok" and reports a subscription as healthy
                    # when its lag could not be read at all.
                    lag = None

            # DLQ depth
            dlq_depth = 0
            with contextlib.suppress(Exception):
                dlq_depth = redis_conn.xlen(f"{stream_category}:dlq")

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
    handler_cls: type[Any],
    stream_name: str,
    broker_name: str,
) -> SubscriptionStatus:
    """Query broker for consumer group info on an external subscriber stream."""
    consumer_group = fqn(handler_cls)

    try:
        with domain.domain_context():
            base_broker = domain.brokers.get(broker_name)
            if not base_broker:
                return _unknown_status(
                    name, handler_cls.__name__, "broker", stream_name
                )

            # Try Redis-style introspection if available
            if hasattr(base_broker, "redis_instance"):
                broker = cast(_RedisStyleBroker, base_broker)
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
                        # See the stream path: an unknown lag must not be
                        # reported as zero.
                        lag = None

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
            info = base_broker.info()
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


def _outbox_processor_names(
    domain: Domain,
) -> list[tuple[str, str, str, str | None]]:
    """The Engine's outbox processors, as ``(name, provider, label, broker)``.

    Mirrors ``Engine._initialize_outbox_processors``: one processor per *managed*
    database provider for the primary broker, plus one per managed provider for
    each broker in ``outbox.external_brokers``, whose name carries an
    ``-external`` suffix. Both details matter: an unmanaged provider runs no
    processor, so reporting one would invent a subscription that does not exist,
    and an external processor that is not named here is invisible even though it
    is the lane most likely to back up.

    The fourth element is the broker whose rows that processor claims, or
    ``None`` when it claims every row. It mirrors ``OutboxProcessor``'s own
    ``_filter_by_broker``: with external brokers configured, each processor takes
    only rows whose ``target_broker`` matches its own, so counting all of them
    would report one combined backlog on every row.

    Without external brokers the answer is ``None``, meaning do not filter. The
    single processor owns every row, so filtering would be a no-op at best, and
    at worst it would drop legacy rows that hold NULL in the column:
    ``_coerce_target_broker`` fills those in on read, in Python, which a SQL
    predicate never sees.
    """
    outbox_config = domain.config.get("outbox", {})
    primary_broker = outbox_config.get("broker", "default")
    external_brokers: list[str] = outbox_config.get("external_brokers", []) or []

    managed = [
        name
        for name, provider in domain.providers.items()
        if getattr(provider, "managed", True)
    ]

    filter_by_broker = bool(external_brokers)

    names: list[tuple[str, str, str, str | None]] = [
        (
            f"outbox-processor-{provider_name}-to-{primary_broker}",
            provider_name,
            f"{provider_name} \u2192 {primary_broker}",
            primary_broker if filter_by_broker else None,
        )
        for provider_name in managed
    ]
    names.extend(
        (
            f"outbox-processor-{provider_name}-to-{broker_name}-external",
            provider_name,
            f"{provider_name} \u2192 {broker_name} (external)",
            broker_name,
        )
        for broker_name in external_brokers
        for provider_name in managed
    )
    return names


def _collect_outbox_statuses(domain: Domain) -> list[SubscriptionStatus]:
    """Collect outbox processor statuses, one per processor the Engine runs."""
    statuses: list[SubscriptionStatus] = []

    if not domain.has_outbox:
        return statuses

    for (
        name,
        database_provider_name,
        stream_label,
        target_broker,
    ) in _outbox_processor_names(domain):
        try:
            with domain.domain_context():
                outbox_repo = domain._get_outbox_repo(database_provider_name)
                counts = outbox_repo.count_by_status(target_broker)

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
    handlers_by_stream: dict[str, list[tuple[str, type[Any]]]] = defaultdict(list)
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
# Checkpoint reset
# ---------------------------------------------------------------------------


def reset_checkpoint_to_head(domain: Domain, status: SubscriptionStatus) -> int:
    """Snap an event-store subscription's checkpoint back to its stream head.

    Writes a fresh ``Read`` position record to ``status.position_stream`` equal to
    the stream head recorded on ``status`` (``head_position``, read during
    verification), the same record shape
    :meth:`EventStoreSubscription.write_position` writes at runtime, and returns
    the head position written.

    A backup restore can leave a checkpoint pointing past the restored head. The
    subscription reads from ``checkpoint + 1``, so it skips every event written
    after the restore. Snapping the checkpoint to the head makes the subscription
    read forward from just after the restored head instead. It writes the head
    observed during verification rather than re-reading a fresh one, so it can
    only move a checkpoint back: ``status`` is flagged beyond head, so its
    ``head_position`` is below its ``current_position``, and writing that head can
    never step the subscription forward over events it has not processed. When the
    restored stream is empty the head is ``-1``, which sends the subscription back
    to the start of the stream.

    Args:
        domain: An initialised Protean domain.
        status: The event-store subscription to reset, flagged beyond head. Its
            ``position_stream`` and numeric ``head_position`` are both set for any
            such subscription read from a reachable store.

    Returns:
        The head position written to the checkpoint stream.

    Raises:
        ValueError: If ``status`` is not an event-store subscription, has no known
            checkpoint stream or head position, or the domain has no event store.
    """
    if status.subscription_type != "event_store":
        raise ValueError(
            f"Cannot reset checkpoint for {status.name!r}: not an event-store "
            f"subscription."
        )
    if not status.position_stream:
        raise ValueError(
            f"Cannot reset checkpoint for {status.name!r}: no checkpoint stream "
            f"is known for it."
        )
    # A beyond-head status always carries a numeric head_position (the verdict
    # parsed it to decide beyond-head); guard for a directly-constructed status.
    if status.head_position is None:
        raise ValueError(
            f"Cannot reset checkpoint for {status.name!r}: its stream head is unknown."
        )
    try:
        head = int(status.head_position)
    except ValueError as exc:
        raise ValueError(
            f"Cannot reset checkpoint for {status.name!r}: its stream head "
            f"{status.head_position!r} is not a number."
        ) from exc

    with domain.domain_context():
        store = domain.event_store.store
        if store is None:
            raise ValueError(
                f"Cannot reset checkpoint for {status.name!r}: the domain has no "
                f"event store configured."
            )

        store._write(
            status.position_stream,
            "Read",
            {"position": head},
            metadata={
                "headers": {
                    "id": str(uuid4()),
                    "type": "Read",
                    "time": domain.clock.now().isoformat(),
                    "stream": status.position_stream,
                },
                "domain": {
                    "kind": MessageType.READ_POSITION.value,
                    "origin_stream": status.stream_category,
                },
            },
        )
    return head


# ---------------------------------------------------------------------------
# Recovery-tracking checkpoints
# ---------------------------------------------------------------------------


@dataclass
class RecoveryCheckpointStatus:
    """A recovery-tracking finding for one event-store subscription.

    An event-store subscription retries a failed position across restarts using
    two durable streams: the ``recovery-checkpoint-{subscriber_name}-{category}``
    stream (a ``watermark`` and an ``unresolved`` snapshot of failed positions
    keyed by ``global_position``) and the ``failed-{subscriber_name}-{category}``
    stream (the ``Failed``/``Resolved``/``Exhausted`` records). On restart the
    subscription reconstructs the set of positions still awaiting recovery from
    the snapshot merged with the failed-stream records after the watermark, then
    re-reads and retries each.

    A restore can leave that set naming positions whose message the restored
    store no longer holds, either because it rolled the category stream back or
    because it removed the specific aggregate stream a position points at. The
    recovery pass re-reads each, finds nothing, and retries it every pass without
    ever resolving it. A ``"stale"`` finding names those positions in
    ``stale_positions``; :func:`reset_recovery_checkpoint` drops them. A
    ``"unknown"`` finding means the recovery streams could not be read (the store
    failed, or a restore left a corrupt checkpoint record), so the subscription
    could not be verified.
    """

    name: str
    """Subscription key (matches ``SubscriptionStatus.name``)."""

    handler_name: str
    """Short class name (e.g. ``"OrderProjector"``)."""

    stream_category: str
    """The category stream the failed positions belong to."""

    recovery_checkpoint_stream: str
    """The durable recovery-checkpoint stream the reset rewrites."""

    head_position: int
    """The category stream head at collection time, reported as context (staleness
    is decided by re-reading each position, not by comparing it to this head)."""

    verdict: str
    """``"stale"`` when the subscription tracks a position whose message is gone,
    ``"unknown"`` when its recovery streams could not be read."""

    stale_positions: list[int]
    """The ``unresolved`` ``global_position`` values whose message the restored
    store no longer holds, sorted ascending. Empty for a ``"unknown"`` finding."""

    unresolved: dict[int, dict[str, Any]] = field(repr=False, compare=False)
    """The full reconstructed unresolved set (``global_position`` -> info),
    carried so the reset can rewrite the checkpoint without a second store read.
    Kept out of reprs and equality, and not part of the reported payload."""

    watermark: int = field(repr=False, compare=False)
    """The failed-stream position the reconstruction read up to, written back so
    the next restart's rebuild resumes past the records already read. Kept out of
    reprs and equality, and not part of the reported payload."""


def _collect_one_recovery_checkpoint(
    domain: Domain, status: SubscriptionStatus
) -> RecoveryCheckpointStatus | None:
    """Find the recovery-tracking entries a restore left pointing at a gone message.

    Returns a ``"stale"`` :class:`RecoveryCheckpointStatus` when the
    subscription tracks at least one unresolved position whose message the
    restored store no longer holds: it re-reads each the same way the recovery
    pass does (the record's specific stream and position when present, else the
    category stream at the global position) and flags every one that comes back
    empty. That catches both a rolled-back category and a removed specific stream
    that still sits below the category head. Confirmed stale positions are
    reported even when a sibling position could not be re-read. A ``"unknown"``
    finding means the recovery streams could not be read at all (the store failed
    mid-collection, a restore left a corrupt checkpoint record, or every remaining
    position's re-read raised), so an unverifiable subscription is reported rather
    than silently passed as clean.

    It reads the stream head itself rather than taking it from ``status``, so it
    still runs when the read-position collection failed and left ``status`` with
    no head (an unreadable read-position checkpoint does not hide readable
    recovery tracking). Returns ``None`` when there is nothing to report: the
    subscription is not an event-store one, it has no recovery-tracking streams,
    or every tracked position's message is still present.
    """
    if status.subscription_type != "event_store":
        return None
    if not status.recovery_checkpoint_stream or not status.failed_positions_stream:
        return None

    stale_positions: list[int] = []
    any_unverified = False
    head = -1
    try:
        with domain.domain_context():
            store = domain.event_store.store
            if store is None:
                return _recovery_unknown(status)
            # Read the head here, not from ``status``: the recovery lane must run
            # even when the read-position collection failed (its ``status`` then
            # carries no head), so a subscription with an unreadable read-position
            # checkpoint but readable recovery streams is not skipped. The head is
            # reported context only; staleness is decided by the per-position
            # re-read below.
            head = store.stream_head_position(status.stream_category)
            unresolved, _watermark, _read = reconstruct_unresolved(
                store,
                status.recovery_checkpoint_stream,
                status.failed_positions_stream,
            )
            # A position is stale when the recovery pass's own re-read would find
            # nothing. Comparing the global position to the category head alone
            # would miss a removed specific stream whose position still sits below
            # the head (another aggregate has a later event). Re-read each on its
            # own: a read error on one position (say a corrupt message in its
            # stream) must not discard the stale entries already confirmed, which
            # a plain comprehension would by aborting the whole scan.
            for pos, info in unresolved.items():
                try:
                    found = read_recovery_message(
                        store, status.stream_category, pos, info
                    )
                except Exception as exc:
                    logger.warning(
                        "Could not re-read recovery position %s for %s: %s",
                        pos,
                        status.name,
                        exc,
                    )
                    any_unverified = True
                    continue
                if not found:
                    stale_positions.append(pos)
            stale_positions.sort()
    except Exception as exc:
        # The reconstruction (or a store-wide failure) can raise on its own: a
        # store error, or a corrupt checkpoint record left by a partial restore.
        # Report it as unverified rather than folding it into "clean", which is
        # the exact falsehood this command exists to catch.
        logger.warning(
            "Could not verify recovery tracking for %s (stream %s): %s",
            status.name,
            status.recovery_checkpoint_stream,
            exc,
        )
        return _recovery_unknown(status)

    # Confirmed stale entries are reported (and reset) even when a sibling could
    # not be re-read. Only when nothing was confirmed stale does a read error make
    # the whole subscription unverified.
    if not stale_positions:
        return _recovery_unknown(status) if any_unverified else None

    return RecoveryCheckpointStatus(
        name=status.name,
        handler_name=status.handler_name,
        stream_category=status.stream_category,
        recovery_checkpoint_stream=status.recovery_checkpoint_stream,
        head_position=head,
        verdict="stale",
        stale_positions=stale_positions,
        unresolved=unresolved,
        watermark=_watermark,
    )


def _recovery_unknown(status: SubscriptionStatus) -> RecoveryCheckpointStatus:
    """Build an unverified recovery finding for a subscription whose recovery
    tracking could not be read.

    ``head_position`` is reported as context only, so it falls back to the
    read-position collection's head when one was recorded and to ``-1`` when it
    was not (an unverifiable head is not what makes the finding ``unknown``)."""
    head = _parse_position(status.head_position)
    return RecoveryCheckpointStatus(
        name=status.name,
        handler_name=status.handler_name,
        stream_category=status.stream_category,
        recovery_checkpoint_stream=status.recovery_checkpoint_stream or "",
        head_position=head if head is not None else -1,
        verdict="unknown",
        stale_positions=[],
        unresolved={},
        watermark=0,
    )


def collect_recovery_checkpoint_statuses(
    domain: Domain, statuses: list[SubscriptionStatus]
) -> list[RecoveryCheckpointStatus]:
    """Return the recovery-tracking findings across the given subscriptions.

    One :class:`RecoveryCheckpointStatus` per event-store subscription that tracks
    a position whose message is gone (verdict ``"stale"``) or whose recovery
    streams could not be read (verdict ``"unknown"``); a subscription that
    verifies clean is omitted. This is read-only: it never writes to any
    recovery-tracking stream.
    """
    findings: list[RecoveryCheckpointStatus] = []
    for status in statuses:
        finding = _collect_one_recovery_checkpoint(domain, status)
        if finding is not None:
            findings.append(finding)
    return findings


def _parse_position(position: str | None) -> int | None:
    """Parse a stored position string to an int, or ``None`` if it cannot.

    Event-store positions are numeric strings (``"-1"``, ``"42"``), but this
    runs against restored or foreign stores, so a position can be missing
    (``None``) or non-numeric. Either way it cannot be compared, so treat it as
    unknown instead of raising.
    """
    if position is None:
        return None
    try:
        return int(position)
    except (TypeError, ValueError):
        return None


def reset_recovery_checkpoint(
    domain: Domain, finding: RecoveryCheckpointStatus
) -> list[int]:
    """Drop the stale unresolved positions from a subscription's recovery
    checkpoint.

    ``finding.stale_positions`` are the positions whose message the restored store
    no longer holds (found by re-reading each, not by comparing to the stream
    head, so a removed specific aggregate stream below the head counts too). This
    writes one fresh ``Checkpoint`` record to ``finding.recovery_checkpoint_stream``
    carrying the reconstructed unresolved set with those positions removed and
    ``finding.watermark`` (the failed-stream position the reconstruction read up
    to). On restart the subscription restores this pruned snapshot and, because
    the watermark sits past the failed-stream records the reconstruction already
    read, its rebuild does not re-read the record naming a stale position and
    re-add it. Every position whose message is still present is preserved.

    Args:
        domain: An initialised Protean domain.
        finding: A ``"stale"`` recovery finding, from
            :func:`collect_recovery_checkpoint_statuses`.

    Returns:
        The positions removed (``finding.stale_positions``).

    Raises:
        ValueError: If ``finding`` is not a ``"stale"`` finding (an ``"unknown"``
            one carries an empty snapshot, so writing it would wipe the
            subscription's real recovery state), or the domain has no event store.
    """
    if finding.verdict != "stale":
        # An "unknown" finding could not be reconstructed, so its `unresolved` is
        # empty; writing it would replace the subscription's real snapshot with a
        # blank one. Refuse rather than reset destructively.
        raise ValueError(
            f"Cannot reset recovery checkpoint for {finding.name!r}: its verdict "
            f"is {finding.verdict!r}, not 'stale'."
        )

    stale = set(finding.stale_positions)
    pruned = {pos: info for pos, info in finding.unresolved.items() if pos not in stale}

    with domain.domain_context():
        store = domain.event_store.store
        if store is None:
            raise ValueError(
                f"Cannot reset recovery checkpoint for {finding.name!r}: the "
                f"domain has no event store configured."
            )

        write_recovery_checkpoint_record(
            store,
            finding.recovery_checkpoint_stream,
            finding.stream_category,
            domain.clock.now().isoformat(),
            finding.watermark,
            pruned,
        )
    return finding.stale_positions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_dict(value: object) -> dict[str, Any] | None:
    """Return *value* as a dict, JSON-decoding a string first, else ``None``."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, dict) else None


def _extract_position_time(last_msg: dict[str, Any] | None) -> str | None:
    """Pull the ISO timestamp of a position write from its stored message.

    ``write_position`` stamps ``metadata.headers.time``; some stores also expose a
    top-level ``time``. Some adapters return that value as a ``datetime`` rather
    than a string, so normalize to ISO format. Returns ``None`` when no message or
    timestamp is present.
    """
    if not last_msg:
        return None
    raw = last_msg.get("time")
    if not raw:
        metadata = _as_dict(last_msg.get("metadata"))
        headers = _as_dict(metadata.get("headers")) if metadata else None
        raw = headers.get("time") if headers else None
    if isinstance(raw, datetime):
        return raw.isoformat()
    return raw if isinstance(raw, str) else None


def _parse_time(iso_value: str | None) -> datetime | None:
    """Parse an ISO timestamp into an aware UTC datetime, or ``None``."""
    if not iso_value:
        return None
    try:
        # ``fromisoformat`` does not reliably accept a trailing ``Z``; normalize
        # to ``+00:00`` so timestamps from any adapter parse consistently.
        parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return ensure_utc_aware(parsed)


def _lag_seconds(
    lag: int | None, last_updated: str | None, now: datetime
) -> float | None:
    """Seconds a subscription is behind head, mirroring projection staleness.

    ``None`` lag stays ``None`` (unknown seconds). A caught-up subscription
    (``lag == 0``) is ``0.0``. Otherwise the seconds are the wall-clock gap
    since ``last_updated``, clamped to ``0.0`` for clock skew; if
    ``last_updated`` is missing or unparseable the result is ``None``.
    """
    if lag is None:
        return None
    if lag == 0:
        return 0.0
    parsed = _parse_time(last_updated)
    if parsed is None:
        return None
    # Clamp clock skew (position timestamp slightly ahead of now) to 0.
    return max(0.0, (now - parsed).total_seconds())


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
