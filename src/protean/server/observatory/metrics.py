"""Prometheus metrics endpoint for the Protean Observatory.

Exposes metrics in Prometheus text exposition format, suitable for scraping
by Prometheus or any compatible monitoring system.

**Hybrid approach:**

When OpenTelemetry is installed and telemetry is enabled, the endpoint serves
OTel-generated Prometheus text (via ``PrometheusMetricReader``) combined with
infrastructure gauges registered as ``ObservableGauge`` callbacks.

When OTel is not installed (or telemetry is disabled), the endpoint falls back
to a hand-rolled text format. The fallback emits the same infrastructure
gauges, plus the stream and per-consumer gauges that the OTel path does not
register. It emits none of the OTel counters and histograms.

**Naming convention:**

OTEL instrument names use dot notation (``protean.db.pool_size``).  When
exported to Prometheus, dots are automatically converted to underscores
(``protean_db_pool_size``).  The hand-rolled fallback uses the underscore
form directly.

Infrastructure gauges (OTEL instrument name / Prometheus text name):

- protean.outbox.pending_count — Pending outbox messages per domain
- protean.subscription.consumer_lag — Messages behind stream head per subscription
- protean.subscription.lag_seconds — Seconds since a subscription's last processed position
- protean.subscription.pending_messages — Unacknowledged messages per subscription
- protean_subscription_dlq_depth — Dead letter queue depth per subscription
- protean_subscription_status — Subscription health (1=ok, 0=not ok)
- protean.projection.staleness_seconds — Seconds a projection is behind its source events
- protean.db.pool_size — Database connection pool size
- protean.db.pool_checked_out — Checked out database connections
- protean.db.pool_overflow — Overflow database connections
- protean.db.pool_checked_in — Available database connections
- protean.broker.pool_active_connections — Broker pool active connections
- protean_broker_up — Broker health (1=up, 0=down)
- protean_broker_memory_bytes — Broker memory usage
- protean_broker_connected_clients — Broker connected clients
- protean_broker_ops_per_sec — Broker operations per second

Plus OTel counters and histograms when telemetry is active:

- protean.command.processed, protean.handler.invocations, protean.uow.commits
- protean.outbox.published, protean.outbox.failed
- protean.command.duration, protean.handler.duration
- protean.uow.events_per_commit, protean.outbox.latency
"""

import logging
import time
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, Any, TypeVar, cast

from fastapi import Response

from protean.domain import Domain
from protean.utils.telemetry import (
    _TELEMETRY_INIT_KEY,
    create_observation,
    get_meter,
    get_meter_provider,
    get_prometheus_text,
)

if TYPE_CHECKING:
    from protean.port.broker import BaseBroker
    from protean.server.projection_status import ProjectionStatus
    from protean.server.subscription_status import SubscriptionStatus

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# ---------------------------------------------------------------------------
# Per-scrape cache
# ---------------------------------------------------------------------------


class _ScrapeCache:
    """Time-based cache that avoids redundant collection within a scrape cycle.

    OTEL observable gauge callbacks fire sequentially during a single
    Prometheus scrape.  Without caching, each callback independently
    calls the same collection helper. For example, each subscription gauge
    callback would query ``_collect_subscription_statuses()`` again.

    This cache stores the result for ``ttl_seconds`` (default 2 s) so
    all callbacks in the same scrape share one collection.
    """

    def __init__(self, ttl_seconds: float = 2.0) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, collector: Callable[[], _T]) -> _T:
        """Return cached value or call *collector* and cache it."""
        now = time.monotonic()
        entry = self._data.get(key)
        if entry is not None:
            ts, value = entry
            if now - ts < self._ttl:
                return cast("_T", value)
        value = collector()
        self._data[key] = (now, value)
        return value

    def clear(self) -> None:
        """Discard all cached entries."""
        self._data.clear()


# Module-level cache instance shared across gauge callbacks
_scrape_cache = _ScrapeCache()

# ---------------------------------------------------------------------------
# Shared data collection helpers
# ---------------------------------------------------------------------------


def _collect_subscription_statuses(
    domains: list[Domain],
) -> list[tuple[Domain, "SubscriptionStatus"]]:
    """Collect subscription statuses from all domains.

    Results are cached for the duration of a single scrape cycle so
    multiple gauge callbacks reuse the same data.
    """

    def _do_collect() -> list[tuple[Domain, "SubscriptionStatus"]]:
        from protean.server.subscription_status import (  # noqa: PLC0415
            collect_subscription_statuses,
        )

        results: list[tuple[Domain, SubscriptionStatus]] = []
        for domain in domains:
            try:
                statuses = collect_subscription_statuses(domain)
                results.extend((domain, s) for s in statuses)
            except Exception as exc:  # noqa: BLE001 - one domain's failure must not stop the scrape
                logger.debug(
                    "Shared collection: subscription status failed for %s: %s",
                    domain.name,
                    exc,
                )
        return results

    return _scrape_cache.get("subscription_statuses", _do_collect)


def _collect_projection_statuses(
    domains: list[Domain],
) -> list[tuple[Domain, "ProjectionStatus"]]:
    """Collect projection statuses from all domains.

    Cached per scrape cycle so the gauge callback and any other consumer reuse
    the same data. Returns ``(domain, ProjectionStatus)`` tuples.
    """

    def _do_collect() -> list[tuple[Domain, "ProjectionStatus"]]:
        from protean.server.projection_status import (  # noqa: PLC0415
            collect_projection_statuses,
        )

        results: list[tuple[Domain, ProjectionStatus]] = []
        for domain in domains:
            try:
                # Scrape path only reads staleness; skip the row COUNT queries.
                results.extend(
                    (domain, s)
                    for s in collect_projection_statuses(
                        domain, include_row_count=False
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one domain's failure must not stop the scrape
                logger.debug(
                    "Shared collection: projection status failed for %s: %s",
                    domain.name,
                    exc,
                )
        return results

    return _scrape_cache.get("projection_statuses", _do_collect)


def _collect_pool_stats(
    domains: list[Domain],
) -> list[tuple[str, str, dict[str, int]]]:
    """Collect connection pool statistics from all providers across domains.

    Returns a list of ``(provider_name, database_type, stats_dict)`` tuples.
    """

    def _do_collect() -> list[tuple[str, str, dict[str, int]]]:
        results: list[tuple[str, str, dict[str, int]]] = []
        for domain in domains:
            try:
                _append_provider_pool_stats(results, domain)
            except Exception as exc:  # noqa: BLE001 - one domain's failure must not stop the scrape
                logger.debug(
                    "Shared collection: pool stats failed for %s: %s",
                    domain.name,
                    exc,
                )
        return results

    return _scrape_cache.get("pool_stats", _do_collect)


def _append_provider_pool_stats(
    results: list[tuple[str, str, dict[str, int]]], domain: Domain
) -> None:
    """Append a row for each provider of *domain* that reports pool statistics.

    Rows go into *results* one at a time, so a provider that raises leaves the
    rows of the providers before it in place.
    """
    with domain.domain_context():
        providers = domain.providers
        if providers and providers._providers:
            for name, provider in providers._providers.items():
                stats = provider.pool_stats()
                if stats:
                    db_type = getattr(provider, "__database__", "unknown")
                    results.append((name, db_type, stats))


def _collect_broker_pool_stats(
    domains: list[Domain],
) -> list[tuple[str, int, int, int]]:
    """Collect broker connection pool statistics.

    Returns a list of ``(broker_name, active, available, max_conn)`` tuples.
    """

    def _do_collect() -> list[tuple[str, int, int, int]]:
        results: list[tuple[str, int, int, int]] = []
        for domain in domains:
            try:
                _append_broker_pool_stats(results, domain)
            except Exception as exc:  # noqa: BLE001 - one domain's failure must not stop the scrape
                logger.debug(
                    "Shared collection: broker pool stats failed for %s: %s",
                    domain.name,
                    exc,
                )
        return results

    return _scrape_cache.get("broker_pool_stats", _do_collect)


def _append_broker_pool_stats(
    results: list[tuple[str, int, int, int]], domain: Domain
) -> None:
    """Append a row for each broker of *domain* that has a Redis connection pool.

    Rows go into *results* one at a time, so a broker that raises leaves the
    rows of the brokers before it in place.
    """
    with domain.domain_context():
        brokers = domain.brokers
        if brokers and brokers._brokers:
            for name, broker in brokers._brokers.items():
                row = _broker_pool_row(name, broker)
                if row is not None:
                    results.append(row)


def _broker_pool_row(
    name: str, broker: "BaseBroker"
) -> tuple[str, int, int, int] | None:
    """Return ``(name, active, available, max_conn)`` for *broker*'s Redis pool.

    Returns ``None`` when the broker has no Redis instance or no pool.
    """
    redis_inst = getattr(broker, "redis_instance", None)
    if redis_inst is None:
        return None
    pool = getattr(redis_inst, "connection_pool", None)
    if pool is None:
        return None
    created = getattr(pool, "_created_connections", 0)
    available = len(getattr(pool, "_available_connections", []))
    max_conn = getattr(pool, "max_connections", 0)
    active = created - available
    return (name, active, available, max_conn)


# ---------------------------------------------------------------------------
# ObservableGauge registration (for infrastructure metrics via OTel)
# ---------------------------------------------------------------------------

_GAUGES_REGISTERED_KEY = "_otel_infra_gauges_registered"


def _register_infrastructure_gauges(domains: list[Domain]) -> None:
    """Register ``ObservableGauge`` callbacks on the first domain with an active meter.

    These callbacks are invoked on every Prometheus scrape and yield the
    outbox, broker, subscription, pool, broker pool and projection gauges.
    The stream and per-consumer gauges of the hand-rolled endpoint are not
    registered.
    """
    if not domains:
        return

    target_domain = _first_domain_with_meter(domains)
    if target_domain is None:
        return

    # Only register once per domain lifetime
    if getattr(target_domain, _GAUGES_REGISTERED_KEY, False):
        return

    meter = get_meter(target_domain, name="protean.infrastructure")

    _register_outbox_gauge(meter, domains)
    _register_broker_gauges(meter, target_domain)
    _register_subscription_gauges(meter, domains)
    _register_pool_gauges(meter, domains)
    _register_broker_pool_gauge(meter, domains)
    _register_projection_gauge(meter, domains)

    setattr(target_domain, _GAUGES_REGISTERED_KEY, True)


def _first_domain_with_meter(domains: list[Domain]) -> Domain | None:
    """Return the first domain that went through ``init_telemetry()`` and has a meter provider."""
    # The init flag check prevents MagicMock/test doubles from matching.
    for d in domains:
        if (
            getattr(d, _TELEMETRY_INIT_KEY, False) is True
            and get_meter_provider(d) is not None
        ):
            return d
    return None


# --- Outbox gauges ---


def _register_outbox_gauge(meter: Any, domains: list[Domain]) -> None:
    meter.create_observable_gauge(
        "protean.outbox.pending_count",
        callbacks=[partial(_outbox_observations, domains)],
        description="Current pending outbox messages",
    )


def _outbox_observations(domains: list[Domain], _options: Any) -> list[Any]:
    observations: list[Any] = []
    for domain in domains:
        try:
            with domain.domain_context():
                outbox_repo = domain._get_outbox_repo("default")
                counts = outbox_repo.count_by_status()
                pending_total = counts.get("pending", 0)
                observations.append(
                    create_observation(
                        pending_total,
                        {"domain": domain.name},
                    )
                )
        except Exception as exc:  # noqa: BLE001 - a gauge callback must not raise into the SDK
            logger.debug(
                "Gauge callback: outbox query failed for %s: %s", domain.name, exc
            )
    return observations


# --- Broker gauges ---


def _register_broker_gauges(meter: Any, target_domain: Domain) -> None:
    meter.create_observable_gauge(
        "protean_broker_up",
        callbacks=[
            partial(_broker_observations, target_domain, "broker_up", _broker_up)
        ],
        description="Broker health (1=up, 0=down)",
    )
    meter.create_observable_gauge(
        "protean_broker_memory_bytes",
        callbacks=[
            partial(
                _broker_observations,
                target_domain,
                "broker_memory",
                _broker_used_memory,
            )
        ],
        description="Broker memory usage in bytes",
        unit="By",
    )
    meter.create_observable_gauge(
        "protean_broker_connected_clients",
        callbacks=[
            partial(
                _broker_observations,
                target_domain,
                "broker_clients",
                _broker_connected_clients,
            )
        ],
        description="Number of connected broker clients",
    )
    meter.create_observable_gauge(
        "protean_broker_ops_per_sec",
        callbacks=[
            partial(
                _broker_observations, target_domain, "broker_ops", _broker_ops_per_sec
            )
        ],
        description="Broker operations per second",
        unit="{operation}/s",
    )


def _broker_observations(
    target_domain: Domain,
    query: str,
    read_value: Callable[[dict[str, Any]], Any],
    _options: Any,
) -> list[Any]:
    """Observe *read_value* of the default broker's health stats, or 0 when it cannot."""
    try:
        with target_domain.domain_context():
            broker = target_domain.brokers.get("default")
            if broker:
                return [create_observation(read_value(broker.health_stats()))]
    except Exception as exc:  # noqa: BLE001 - a gauge callback must not raise into the SDK
        logger.debug("Gauge callback: %s query failed: %s", query, exc)
    return [create_observation(0)]


def _broker_up(health: dict[str, Any]) -> int:
    details = health.get("details", {})
    return 1 if health.get("connected") and details.get("healthy") else 0


def _broker_used_memory(health: dict[str, Any]) -> Any:
    return health.get("details", {}).get("used_memory", 0)


def _broker_connected_clients(health: dict[str, Any]) -> Any:
    return health.get("details", {}).get("connected_clients", 0)


def _broker_ops_per_sec(health: dict[str, Any]) -> Any:
    return health.get("details", {}).get("instantaneous_ops_per_sec", 0)


# --- Subscription gauges (shared collection) ---


def _register_subscription_gauges(meter: Any, domains: list[Domain]) -> None:
    for metric_name, field, description, transform in [
        (
            "protean.subscription.consumer_lag",
            "lag",
            "Messages behind stream head",
            None,
        ),
        (
            "protean.subscription.pending_messages",
            "pending",
            "Unacknowledged messages",
            None,
        ),
        (
            "protean_subscription_dlq_depth",
            "dlq_depth",
            "Dead letter queue depth",
            None,
        ),
        (
            "protean_subscription_status",
            "status",
            "Subscription health (1=ok, 0=not ok)",
            _status_flag,
        ),
    ]:
        meter.create_observable_gauge(
            metric_name,
            callbacks=[partial(_subscription_observations, domains, field, transform)],
            description=description,
        )

    # Seconds-behind gets its own registration (not another row in the loop
    # above) because that loop cannot set a unit, and this gauge carries `s`.
    # The shared callback already skips None, so unavailable seconds are simply
    # not reported.
    meter.create_observable_gauge(
        "protean.subscription.lag_seconds",
        callbacks=[partial(_subscription_observations, domains, "lag_seconds", None)],
        description="Seconds since a subscription's last processed position",
        unit="s",
    )


def _status_flag(status: Any) -> int:
    return 1 if status == "ok" else 0


def _subscription_observations(
    domains: list[Domain],
    field: str,
    transform: Callable[[Any], Any] | None,
    _options: Any,
) -> list[Any]:
    observations: list[Any] = []
    for domain, s in _collect_subscription_statuses(domains):
        attrs = {
            "domain": domain.name,
            "handler": s.handler_name,
            "stream": s.stream_category,
            "type": s.subscription_type,
        }
        value = getattr(s, field)
        if transform is not None:
            value = transform(value)
        if value is not None:
            observations.append(create_observation(value, attrs))
    return observations


# --- Database connection pool gauges ---


def _register_pool_gauges(meter: Any, domains: list[Domain]) -> None:
    for stat_key, metric_name, description in [
        ("size", "protean.db.pool_size", "Database connection pool size"),
        (
            "checked_out",
            "protean.db.pool_checked_out",
            "Checked out database connections",
        ),
        ("overflow", "protean.db.pool_overflow", "Overflow database connections"),
        ("checked_in", "protean.db.pool_checked_in", "Available database connections"),
    ]:
        meter.create_observable_gauge(
            metric_name,
            callbacks=[partial(_pool_observations, domains, stat_key)],
            description=description,
            unit="{connection}",
        )


def _pool_observations(
    domains: list[Domain], stat_key: str, _options: Any
) -> list[Any]:
    observations: list[Any] = []
    for name, db_type, stats in _collect_pool_stats(domains):
        attrs = {"provider_name": name, "database_type": db_type}
        observations.append(create_observation(stats.get(stat_key, 0), attrs))
    return observations


# --- Broker connection pool gauges ---


def _register_broker_pool_gauge(meter: Any, domains: list[Domain]) -> None:
    meter.create_observable_gauge(
        "protean.broker.pool_active_connections",
        callbacks=[partial(_broker_pool_active_observations, domains)],
        description="Active broker pool connections",
        unit="{connection}",
    )


def _broker_pool_active_observations(domains: list[Domain], _options: Any) -> list[Any]:
    observations: list[Any] = []
    for name, active, _available, _max_conn in _collect_broker_pool_stats(domains):
        observations.append(create_observation(active, {"broker_name": name}))
    return observations


# --- Projection staleness gauge (shared collection) ---


def _register_projection_gauge(meter: Any, domains: list[Domain]) -> None:
    meter.create_observable_gauge(
        "protean.projection.staleness_seconds",
        callbacks=[partial(_projection_staleness_observations, domains)],
        description="Seconds a projection is behind its source events",
        unit="s",
    )


def _projection_staleness_observations(
    domains: list[Domain], _options: Any
) -> list[Any]:
    observations: list[Any] = []
    for domain, p in _collect_projection_statuses(domains):
        if p.staleness_seconds is None:
            continue
        observations.append(
            create_observation(
                p.staleness_seconds,
                {"domain": domain.name, "projection": p.projection_name},
            )
        )
    return observations


# ---------------------------------------------------------------------------
# Hand-rolled fallback (used when OTel is not installed)
# ---------------------------------------------------------------------------


def _hand_rolled_metrics(domains: list[Domain]) -> str:
    """Generate Prometheus text exposition using hand-rolled formatting.

    Used when OTel is not installed or telemetry is disabled.
    """
    lines: list[str] = []

    _append_outbox_lines(lines, domains)
    _append_broker_lines(lines, domains)
    _append_subscription_lines(lines, domains)
    _append_projection_lines(lines, domains)
    _append_consumer_lines(lines, domains)
    _append_pool_lines(lines, domains)
    _append_broker_pool_lines(lines, domains)

    lines.append("")  # Trailing newline
    return "\n".join(lines)


# Each section helper below appends to ``lines`` as it goes, so a section that
# fails part-way keeps the lines it wrote before the failure.


def _append_gauge_header(lines: list[str], name: str, help_text: str) -> None:
    """Append a blank line and the ``HELP`` and ``TYPE gauge`` lines for *name*."""
    lines.append("")
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")


def _append_outbox_lines(lines: list[str], domains: list[Domain]) -> None:
    lines.append("# HELP protean_outbox_pending_count Current pending outbox messages")
    lines.append("# TYPE protean_outbox_pending_count gauge")

    for domain in domains:
        try:
            with domain.domain_context():
                outbox_repo = domain._get_outbox_repo("default")
                counts = outbox_repo.count_by_status()
                pending_total = counts.get("pending", 0)
                lines.append(
                    f'protean_outbox_pending_count{{domain="{domain.name}"}} {pending_total}'
                )
        except Exception as e:  # noqa: BLE001 - one section's failure must not stop the scrape
            logger.debug(f"Metrics: outbox query failed for {domain.name}: {e}")


def _append_broker_lines(lines: list[str], domains: list[Domain]) -> None:
    """Append the broker and stream gauges read from the first domain's broker."""
    try:
        first_domain = domains[0]
        with first_domain.domain_context():
            broker = first_domain.brokers.get("default")
            if broker:
                _append_broker_health_lines(lines, broker.health_stats())
    except Exception as e:  # noqa: BLE001 - one section's failure must not stop the scrape
        logger.debug(f"Metrics: broker query failed: {e}")


def _append_broker_health_lines(lines: list[str], health: dict[str, Any]) -> None:
    details = health.get("details", {})
    is_connected = health.get("connected", False)

    _append_gauge_header(lines, "protean_broker_up", "Broker health (1=up, 0=down)")
    lines.append(
        f"protean_broker_up {1 if is_connected and details.get('healthy') else 0}"
    )

    _append_gauge_header(
        lines, "protean_broker_memory_bytes", "Broker memory usage in bytes"
    )
    lines.append(f"protean_broker_memory_bytes {details.get('used_memory', 0)}")

    _append_gauge_header(
        lines,
        "protean_broker_connected_clients",
        "Number of connected broker clients",
    )
    lines.append(
        f"protean_broker_connected_clients {details.get('connected_clients', 0)}"
    )

    _append_gauge_header(
        lines, "protean_broker_ops_per_sec", "Broker operations per second"
    )
    lines.append(
        f"protean_broker_ops_per_sec {details.get('instantaneous_ops_per_sec', 0)}"
    )

    message_counts = details.get("message_counts", {})
    _append_gauge_header(
        lines, "protean_stream_messages_total", "Total messages in streams"
    )
    lines.append(
        f"protean_stream_messages_total {message_counts.get('total_messages', 0)}"
    )

    _append_gauge_header(
        lines, "protean_stream_pending", "Pending (in-flight) messages"
    )
    lines.append(f"protean_stream_pending {message_counts.get('in_flight', 0)}")

    streams_info = details.get("streams", {})
    _append_gauge_header(lines, "protean_streams_count", "Number of active streams")
    lines.append(f"protean_streams_count {streams_info.get('count', 0)}")

    cg_info = details.get("consumer_groups", {})
    _append_gauge_header(
        lines, "protean_consumer_groups_count", "Number of consumer groups"
    )
    lines.append(f"protean_consumer_groups_count {cg_info.get('count', 0)}")


def _append_subscription_lines(lines: list[str], domains: list[Domain]) -> None:
    try:
        collected = _collect_subscription_statuses(domains)
        if collected:
            _append_gauge_header(
                lines,
                "protean_subscription_consumer_lag",
                "Messages behind stream head",
            )
            _append_gauge_header(
                lines,
                "protean_subscription_pending_messages",
                "Unacknowledged messages",
            )
            _append_gauge_header(
                lines, "protean_subscription_dlq_depth", "Dead letter queue depth"
            )
            _append_gauge_header(
                lines,
                "protean_subscription_status",
                "Subscription health (1=ok, 0=not ok)",
            )
            _append_gauge_header(
                lines,
                "protean_subscription_lag_seconds",
                "Seconds since a subscription's last processed position",
            )

            for domain, s in collected:
                _append_subscription_rows(lines, domain, s)
    except Exception as e:  # noqa: BLE001 - one section's failure must not stop the scrape
        logger.debug(f"Metrics: subscription status failed: {e}")


def _append_subscription_rows(
    lines: list[str], domain: Domain, s: "SubscriptionStatus"
) -> None:
    labels = (
        f'domain="{domain.name}",'
        f'handler="{s.handler_name}",'
        f'stream="{s.stream_category}",'
        f'type="{s.subscription_type}"'
    )
    if s.lag is not None:
        lines.append(f"protean_subscription_consumer_lag{{{labels}}} {s.lag}")
    if s.lag_seconds is not None:
        lines.append(f"protean_subscription_lag_seconds{{{labels}}} {s.lag_seconds}")
    lines.append(f"protean_subscription_pending_messages{{{labels}}} {s.pending}")
    lines.append(f"protean_subscription_dlq_depth{{{labels}}} {s.dlq_depth}")
    lines.append(
        f"protean_subscription_status{{{labels}}} {1 if s.status == 'ok' else 0}"
    )


def _append_projection_lines(lines: list[str], domains: list[Domain]) -> None:
    try:
        projections = _collect_projection_statuses(domains)
        if projections:
            _append_gauge_header(
                lines,
                "protean_projection_staleness_seconds",
                "Seconds a projection is behind its source events",
            )
            for domain, p in projections:
                if p.staleness_seconds is None:
                    continue
                labels = f'domain="{domain.name}",projection="{p.projection_name}"'
                lines.append(
                    f"protean_projection_staleness_seconds{{{labels}}} "
                    f"{p.staleness_seconds}"
                )
    except Exception as e:  # noqa: BLE001 - one section's failure must not stop the scrape
        logger.debug(f"Metrics: projection staleness failed: {e}")


def _append_consumer_lines(lines: list[str], domains: list[Domain]) -> None:
    """Append the per-consumer gauges read with ``XINFO CONSUMERS``."""
    try:
        from protean.server.observatory.api import (  # noqa: PLC0415
            _discover_streams,
            _get_redis,
        )

        redis_conn = _get_redis(domains)
        if redis_conn:
            _append_gauge_header(
                lines,
                "protean_consumer_pending",
                "Per-consumer unacknowledged messages",
            )
            _append_gauge_header(
                lines,
                "protean_consumer_idle_ms",
                "Per-consumer idle time in milliseconds",
            )

            for stream_name in _discover_streams(redis_conn):
                _append_stream_consumer_lines(lines, redis_conn, stream_name)
    except Exception as e:  # noqa: BLE001 - one section's failure must not stop the scrape
        logger.debug(f"Metrics: consumer metrics failed: {e}")


def _append_stream_consumer_lines(
    lines: list[str], redis_conn: Any, stream_name: str
) -> None:
    from protean.server.observatory.api import _xinfo_groups  # noqa: PLC0415

    try:
        groups = _xinfo_groups(redis_conn, stream_name)
        for grp in groups:
            if not isinstance(grp, dict):
                continue
            gname = _decoded_name(grp)
            if not gname:
                continue
            _append_group_consumer_lines(lines, redis_conn, stream_name, gname)
    # one unreadable stream must not drop other metrics; logged
    except Exception:
        logger.debug(
            "Metrics: could not read groups of stream %s",
            stream_name,
            exc_info=True,
        )


def _append_group_consumer_lines(
    lines: list[str], redis_conn: Any, stream_name: str, gname: str
) -> None:
    from protean.server.observatory.api import _xinfo_consumers  # noqa: PLC0415

    try:
        consumers_info = _xinfo_consumers(redis_conn, stream_name, gname)
        for c in consumers_info:
            if not isinstance(c, dict):
                continue
            cname = _decoded_name(c)
            cpending = c.get("pending") or c.get(b"pending") or 0
            cidle = c.get("idle") or c.get(b"idle") or 0
            labels = f'consumer="{cname}",group="{gname}",stream="{stream_name}"'
            lines.append(f"protean_consumer_pending{{{labels}}} {int(cpending)}")
            lines.append(f"protean_consumer_idle_ms{{{labels}}} {int(cidle)}")
    # one unreadable group must not drop other metrics; logged
    except Exception:
        logger.debug(
            "Metrics: could not read consumers of group %s on stream %s",
            gname,
            stream_name,
            exc_info=True,
        )


def _decoded_name(info: dict[Any, Any]) -> Any:
    """Return the ``name`` entry of a Redis ``XINFO`` row, keyed by str or bytes."""
    name = info.get("name") or info.get(b"name")
    if isinstance(name, bytes):
        name = name.decode("utf-8")
    return name


def _append_pool_lines(lines: list[str], domains: list[Domain]) -> None:
    try:
        pool_data = _collect_pool_stats(domains)
        if pool_data:
            _append_gauge_header(
                lines, "protean_db_pool_size", "Database connection pool size"
            )
            _append_gauge_header(
                lines,
                "protean_db_pool_checked_out",
                "Checked out database connections",
            )
            _append_gauge_header(
                lines, "protean_db_pool_overflow", "Overflow database connections"
            )
            _append_gauge_header(
                lines, "protean_db_pool_checked_in", "Available database connections"
            )

            for name, db_type, stats in pool_data:
                labels = f'provider_name="{name}",database_type="{db_type}"'
                lines.append(f"protean_db_pool_size{{{labels}}} {stats.get('size', 0)}")
                lines.append(
                    f"protean_db_pool_checked_out{{{labels}}} {stats.get('checked_out', 0)}"
                )
                lines.append(
                    f"protean_db_pool_overflow{{{labels}}} {stats.get('overflow', 0)}"
                )
                lines.append(
                    f"protean_db_pool_checked_in{{{labels}}} {stats.get('checked_in', 0)}"
                )
    except Exception as e:  # noqa: BLE001 - one section's failure must not stop the scrape
        logger.debug(f"Metrics: pool stats failed: {e}")


def _append_broker_pool_lines(lines: list[str], domains: list[Domain]) -> None:
    try:
        broker_pool_data = _collect_broker_pool_stats(domains)
        if broker_pool_data:
            _append_gauge_header(
                lines,
                "protean_broker_pool_active_connections",
                "Active broker pool connections",
            )

            for name, active, _available, _max_conn in broker_pool_data:
                labels = f'broker_name="{name}"'
                lines.append(
                    f"protean_broker_pool_active_connections{{{labels}}} {active}"
                )
    except Exception as e:  # noqa: BLE001 - one section's failure must not stop the scrape
        logger.debug(f"Metrics: broker pool stats failed: {e}")


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def create_metrics_endpoint(
    domains: list[Domain],
) -> Callable[[], Any]:
    """Create the Prometheus metrics endpoint function.

    When OTel telemetry is enabled on at least one domain **and** the
    ``opentelemetry-exporter-prometheus`` package is installed, the endpoint
    serves OTel-generated Prometheus text.  Infrastructure metrics
    (outbox, broker, subscriptions, database pools, broker pools and
    projection staleness) are exposed as ``ObservableGauge`` callbacks so
    they appear alongside the domain-operation counters and histograms.

    Otherwise, the endpoint serves the hand-rolled Prometheus text.

    Gauge registration is deferred to the first request so that the meter
    provider has time to be fully initialized after domain activation.
    """

    gauges_attempted = False

    async def metrics() -> Response:
        """Prometheus text exposition format metrics."""
        nonlocal gauges_attempted

        # Lazy gauge registration: attempt on first request, not at
        # endpoint creation time, so the meter provider is available.
        if not gauges_attempted:
            _register_infrastructure_gauges(domains)
            gauges_attempted = True

        # Try OTel-powered path first
        for domain in domains:
            otel_text = get_prometheus_text(domain)
            if otel_text is not None:
                return Response(
                    content=otel_text,
                    media_type="text/plain; version=0.0.4; charset=utf-8",
                )

        # Fallback: hand-rolled implementation
        return Response(
            content=_hand_rolled_metrics(domains),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return metrics
