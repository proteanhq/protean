"""Prometheus metrics endpoint for the Protean Observatory.

Exposes metrics in Prometheus text exposition format, suitable for scraping
by Prometheus or any compatible monitoring system.

**Hybrid approach:**

When OpenTelemetry is installed and telemetry is enabled, the endpoint serves
OTel-generated Prometheus text (via ``PrometheusMetricReader``) combined with
hand-rolled infrastructure gauges registered as ``ObservableGauge`` callbacks.

When OTel is not installed (or telemetry is disabled), the endpoint falls back
to the original hand-rolled text format with zero behavioral change.

Metrics:
- protean_outbox_pending (gauge) — Current pending outbox messages per domain
- protean_stream_messages_total (gauge) — Total messages in streams
- protean_stream_pending (gauge) — Pending (unacknowledged) messages
- protean_broker_connected_clients (gauge) — Broker connected clients
- protean_broker_memory_bytes (gauge) — Broker memory usage
- protean_broker_ops_per_sec (gauge) — Broker operations per second
- protean_broker_up (gauge) — Broker health status (1=up, 0=down)
- protean_subscription_lag (gauge) — Messages behind stream head per subscription
- protean_subscription_pending (gauge) — Unacknowledged messages per subscription
- protean_subscription_dlq_depth (gauge) — Dead letter queue depth per subscription
- protean_subscription_status (gauge) — Subscription health (1=ok, 0=not ok)

Plus OTel counters and histograms when telemetry is active:
- protean.command.processed, protean.handler.invocations, protean.uow.commits
- protean.outbox.published, protean.outbox.failed
- protean.command.duration, protean.handler.duration
- protean.uow.events_per_commit, protean.outbox.latency
"""

import logging
from typing import List

from fastapi import Response

from protean.domain import Domain

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ObservableGauge registration (for infrastructure metrics via OTel)
# ---------------------------------------------------------------------------

_GAUGES_REGISTERED_KEY = "_otel_infra_gauges_registered"


def _register_infrastructure_gauges(domains: List[Domain]) -> None:
    """Register ``ObservableGauge`` callbacks on the first domain with an active meter.

    These callbacks are invoked on every Prometheus scrape and yield
    the same infrastructure metrics the hand-rolled endpoint produced.
    """
    if not domains:
        return

    from protean.utils.telemetry import create_observation, get_meter, get_meter_provider

    # Find the first domain that has a configured meter provider
    target_domain: Domain | None = None
    for d in domains:
        if get_meter_provider(d) is not None:
            target_domain = d
            break

    if target_domain is None:
        return

    # Only register once per domain lifetime
    if getattr(target_domain, _GAUGES_REGISTERED_KEY, False):
        return

    meter = get_meter(target_domain, name="protean.infrastructure")

    # --- Outbox gauges ---
    def _outbox_callback(_options):
        observations = []
        for domain in domains:
            try:
                with domain.domain_context():
                    outbox_repo = domain._get_outbox_repo("default")
                    counts = outbox_repo.count_by_status()
                    for status, count in counts.items():
                        observations.append(
                            create_observation(
                                count,
                                {"domain": domain.name, "status": status},
                            )
                        )
            except Exception as exc:
                logger.debug("Gauge callback: outbox query failed for %s: %s", domain.name, exc)
        return observations

    meter.create_observable_gauge(
        "protean_outbox_pending",
        callbacks=[_outbox_callback],
        description="Current pending outbox messages",
    )

    # --- Broker gauges ---
    def _broker_up_callback(_options):
        try:
            with target_domain.domain_context():
                broker = target_domain.brokers.get("default")
                if broker:
                    health = broker.health_stats()
                    details = health.get("details", {})
                    is_up = 1 if health.get("connected") and details.get("healthy") else 0
                    return [create_observation(is_up)]
        except Exception as exc:
            logger.debug("Gauge callback: broker_up query failed: %s", exc)
        return [create_observation(0)]

    def _broker_memory_callback(_options):
        try:
            with target_domain.domain_context():
                broker = target_domain.brokers.get("default")
                if broker:
                    health = broker.health_stats()
                    mem = health.get("details", {}).get("used_memory", 0)
                    return [create_observation(mem)]
        except Exception as exc:
            logger.debug("Gauge callback: broker_memory query failed: %s", exc)
        return [create_observation(0)]

    def _broker_clients_callback(_options):
        try:
            with target_domain.domain_context():
                broker = target_domain.brokers.get("default")
                if broker:
                    health = broker.health_stats()
                    clients = health.get("details", {}).get("connected_clients", 0)
                    return [create_observation(clients)]
        except Exception as exc:
            logger.debug("Gauge callback: broker_clients query failed: %s", exc)
        return [create_observation(0)]

    def _broker_ops_callback(_options):
        try:
            with target_domain.domain_context():
                broker = target_domain.brokers.get("default")
                if broker:
                    health = broker.health_stats()
                    ops = health.get("details", {}).get("instantaneous_ops_per_sec", 0)
                    return [create_observation(ops)]
        except Exception as exc:
            logger.debug("Gauge callback: broker_ops query failed: %s", exc)
        return [create_observation(0)]

    meter.create_observable_gauge(
        "protean_broker_up",
        callbacks=[_broker_up_callback],
        description="Broker health (1=up, 0=down)",
    )
    meter.create_observable_gauge(
        "protean_broker_memory_bytes",
        callbacks=[_broker_memory_callback],
        description="Broker memory usage in bytes",
        unit="By",
    )
    meter.create_observable_gauge(
        "protean_broker_connected_clients",
        callbacks=[_broker_clients_callback],
        description="Number of connected broker clients",
    )
    meter.create_observable_gauge(
        "protean_broker_ops_per_sec",
        callbacks=[_broker_ops_callback],
        description="Broker operations per second",
        unit="{operation}/s",
    )

    # --- Subscription gauges ---
    def _subscription_lag_callback(_options):
        from protean.server.subscription_status import collect_subscription_statuses

        observations = []
        for domain in domains:
            try:
                statuses = collect_subscription_statuses(domain)
                for s in statuses:
                    attrs = {
                        "domain": domain.name,
                        "handler": s.handler_name,
                        "stream": s.stream_category,
                        "type": s.subscription_type,
                    }
                    if s.lag is not None:
                        observations.append(create_observation(s.lag, attrs))
            except Exception as exc:
                logger.debug("Gauge callback: subscription_lag failed for %s: %s", domain.name, exc)
        return observations

    def _subscription_pending_callback(_options):
        from protean.server.subscription_status import collect_subscription_statuses

        observations = []
        for domain in domains:
            try:
                statuses = collect_subscription_statuses(domain)
                for s in statuses:
                    attrs = {
                        "domain": domain.name,
                        "handler": s.handler_name,
                        "stream": s.stream_category,
                        "type": s.subscription_type,
                    }
                    observations.append(create_observation(s.pending, attrs))
            except Exception as exc:
                logger.debug("Gauge callback: subscription_pending failed for %s: %s", domain.name, exc)
        return observations

    def _subscription_dlq_callback(_options):
        from protean.server.subscription_status import collect_subscription_statuses

        observations = []
        for domain in domains:
            try:
                statuses = collect_subscription_statuses(domain)
                for s in statuses:
                    attrs = {
                        "domain": domain.name,
                        "handler": s.handler_name,
                        "stream": s.stream_category,
                        "type": s.subscription_type,
                    }
                    observations.append(create_observation(s.dlq_depth, attrs))
            except Exception as exc:
                logger.debug("Gauge callback: subscription_dlq failed for %s: %s", domain.name, exc)
        return observations

    def _subscription_status_callback(_options):
        from protean.server.subscription_status import collect_subscription_statuses

        observations = []
        for domain in domains:
            try:
                statuses = collect_subscription_statuses(domain)
                for s in statuses:
                    attrs = {
                        "domain": domain.name,
                        "handler": s.handler_name,
                        "stream": s.stream_category,
                        "type": s.subscription_type,
                    }
                    observations.append(
                        create_observation(1 if s.status == "ok" else 0, attrs)
                    )
            except Exception as exc:
                logger.debug("Gauge callback: subscription_status failed for %s: %s", domain.name, exc)
        return observations

    meter.create_observable_gauge(
        "protean_subscription_lag",
        callbacks=[_subscription_lag_callback],
        description="Messages behind stream head",
    )
    meter.create_observable_gauge(
        "protean_subscription_pending",
        callbacks=[_subscription_pending_callback],
        description="Unacknowledged messages",
    )
    meter.create_observable_gauge(
        "protean_subscription_dlq_depth",
        callbacks=[_subscription_dlq_callback],
        description="Dead letter queue depth",
    )
    meter.create_observable_gauge(
        "protean_subscription_status",
        callbacks=[_subscription_status_callback],
        description="Subscription health (1=ok, 0=not ok)",
    )

    setattr(target_domain, _GAUGES_REGISTERED_KEY, True)


# ---------------------------------------------------------------------------
# Hand-rolled fallback (identical to the original implementation)
# ---------------------------------------------------------------------------


def _hand_rolled_metrics(domains: List[Domain]) -> str:
    """Generate Prometheus text exposition using hand-rolled formatting.

    Used when OTel is not installed or telemetry is disabled.
    """
    lines: list[str] = []

    # --- Outbox metrics ---
    lines.append("# HELP protean_outbox_pending Current pending outbox messages")
    lines.append("# TYPE protean_outbox_pending gauge")

    for domain in domains:
        try:
            with domain.domain_context():
                outbox_repo = domain._get_outbox_repo("default")
                counts = outbox_repo.count_by_status()
                for status, count in counts.items():
                    lines.append(
                        f'protean_outbox_messages{{domain="{domain.name}",status="{status}"}} {count}'
                    )
        except Exception as e:
            logger.debug(f"Metrics: outbox query failed for {domain.name}: {e}")

    # --- Broker / stream metrics (from first domain's broker) ---
    try:
        first_domain = domains[0]
        with first_domain.domain_context():
            broker = first_domain.brokers.get("default")
            if broker:
                health = broker.health_stats()
                details = health.get("details", {})
                is_connected = health.get("connected", False)

                lines.append("")
                lines.append(
                    "# HELP protean_broker_up Broker health (1=up, 0=down)"
                )
                lines.append("# TYPE protean_broker_up gauge")
                lines.append(
                    f"protean_broker_up {1 if is_connected and details.get('healthy') else 0}"
                )

                lines.append("")
                lines.append(
                    "# HELP protean_broker_memory_bytes Broker memory usage in bytes"
                )
                lines.append("# TYPE protean_broker_memory_bytes gauge")
                lines.append(
                    f"protean_broker_memory_bytes {details.get('used_memory', 0)}"
                )

                lines.append("")
                lines.append(
                    "# HELP protean_broker_connected_clients Number of connected broker clients"
                )
                lines.append("# TYPE protean_broker_connected_clients gauge")
                lines.append(
                    f"protean_broker_connected_clients {details.get('connected_clients', 0)}"
                )

                lines.append("")
                lines.append(
                    "# HELP protean_broker_ops_per_sec Broker operations per second"
                )
                lines.append("# TYPE protean_broker_ops_per_sec gauge")
                lines.append(
                    f"protean_broker_ops_per_sec {details.get('instantaneous_ops_per_sec', 0)}"
                )

                message_counts = details.get("message_counts", {})
                lines.append("")
                lines.append(
                    "# HELP protean_stream_messages_total Total messages in streams"
                )
                lines.append("# TYPE protean_stream_messages_total gauge")
                lines.append(
                    f"protean_stream_messages_total {message_counts.get('total_messages', 0)}"
                )

                lines.append("")
                lines.append(
                    "# HELP protean_stream_pending Pending (in-flight) messages"
                )
                lines.append("# TYPE protean_stream_pending gauge")
                lines.append(
                    f"protean_stream_pending {message_counts.get('in_flight', 0)}"
                )

                streams_info = details.get("streams", {})
                lines.append("")
                lines.append(
                    "# HELP protean_streams_count Number of active streams"
                )
                lines.append("# TYPE protean_streams_count gauge")
                lines.append(
                    f"protean_streams_count {streams_info.get('count', 0)}"
                )

                cg_info = details.get("consumer_groups", {})
                lines.append("")
                lines.append(
                    "# HELP protean_consumer_groups_count Number of consumer groups"
                )
                lines.append("# TYPE protean_consumer_groups_count gauge")
                lines.append(
                    f"protean_consumer_groups_count {cg_info.get('count', 0)}"
                )

    except Exception as e:
        logger.debug(f"Metrics: broker query failed: {e}")

    # --- Subscription lag metrics ---
    try:
        from protean.server.subscription_status import (
            collect_subscription_statuses,
        )

        lines.append("")
        lines.append("# HELP protean_subscription_lag Messages behind stream head")
        lines.append("# TYPE protean_subscription_lag gauge")
        lines.append("")
        lines.append("# HELP protean_subscription_pending Unacknowledged messages")
        lines.append("# TYPE protean_subscription_pending gauge")
        lines.append("")
        lines.append(
            "# HELP protean_subscription_dlq_depth Dead letter queue depth"
        )
        lines.append("# TYPE protean_subscription_dlq_depth gauge")
        lines.append("")
        lines.append(
            "# HELP protean_subscription_status Subscription health (1=ok, 0=not ok)"
        )
        lines.append("# TYPE protean_subscription_status gauge")

        for domain in domains:
            try:
                statuses = collect_subscription_statuses(domain)
                for s in statuses:
                    labels = (
                        f'domain="{domain.name}",'
                        f'handler="{s.handler_name}",'
                        f'stream="{s.stream_category}",'
                        f'type="{s.subscription_type}"'
                    )
                    if s.lag is not None:
                        lines.append(
                            f"protean_subscription_lag{{{labels}}} {s.lag}"
                        )
                    lines.append(
                        f"protean_subscription_pending{{{labels}}} {s.pending}"
                    )
                    lines.append(
                        f"protean_subscription_dlq_depth{{{labels}}} {s.dlq_depth}"
                    )
                    lines.append(
                        f"protean_subscription_status{{{labels}}} {1 if s.status == 'ok' else 0}"
                    )
            except Exception as e:
                logger.debug(
                    f"Metrics: subscription status failed for {domain.name}: {e}"
                )
    except Exception as e:
        logger.debug(f"Metrics: subscription status import failed: {e}")

    # --- Per-consumer metrics (via XINFO CONSUMERS) ---
    try:
        from protean.server.observatory.api import _discover_streams, _get_redis

        redis_conn = _get_redis(domains)
        if redis_conn:
            lines.append("")
            lines.append(
                "# HELP protean_consumer_pending Per-consumer unacknowledged messages"
            )
            lines.append("# TYPE protean_consumer_pending gauge")
            lines.append("")
            lines.append(
                "# HELP protean_consumer_idle_ms Per-consumer idle time in milliseconds"
            )
            lines.append("# TYPE protean_consumer_idle_ms gauge")

            for stream_name in _discover_streams(redis_conn):
                try:
                    groups = redis_conn.xinfo_groups(stream_name)
                    for grp in groups:
                        if not isinstance(grp, dict):
                            continue
                        gname = grp.get("name") or grp.get(b"name")
                        if isinstance(gname, bytes):
                            gname = gname.decode("utf-8")
                        if not gname:
                            continue

                        try:
                            consumers_info = redis_conn.xinfo_consumers(
                                stream_name, gname
                            )
                            for c in consumers_info:
                                if not isinstance(c, dict):
                                    continue
                                cname = c.get("name") or c.get(b"name")
                                if isinstance(cname, bytes):
                                    cname = cname.decode("utf-8")
                                cpending = (
                                    c.get("pending") or c.get(b"pending") or 0
                                )
                                cidle = c.get("idle") or c.get(b"idle") or 0
                                labels = (
                                    f'consumer="{cname}",'
                                    f'group="{gname}",'
                                    f'stream="{stream_name}"'
                                )
                                lines.append(
                                    f"protean_consumer_pending{{{labels}}} {int(cpending)}"
                                )
                                lines.append(
                                    f"protean_consumer_idle_ms{{{labels}}} {int(cidle)}"
                                )
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Metrics: consumer metrics failed: {e}")

    lines.append("")  # Trailing newline
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def create_metrics_endpoint(domains: List[Domain]):
    """Create the Prometheus metrics endpoint function.

    When OTel telemetry is enabled on at least one domain **and** the
    ``opentelemetry-exporter-prometheus`` package is installed, the endpoint
    serves OTel-generated Prometheus text.  Infrastructure metrics
    (outbox, broker, subscriptions) are exposed as ``ObservableGauge``
    callbacks so they appear alongside the domain-operation counters and
    histograms.

    Otherwise, the endpoint falls back to the original hand-rolled
    implementation with zero behavioral change.

    Gauge registration is deferred to the first request so that the meter
    provider has time to be fully initialized after domain activation.
    """

    gauges_attempted = False

    async def metrics():
        """Prometheus text exposition format metrics."""
        nonlocal gauges_attempted

        # Lazy gauge registration: attempt on first request, not at
        # endpoint creation time, so the meter provider is available.
        if not gauges_attempted:
            _register_infrastructure_gauges(domains)
            gauges_attempted = True

        from protean.utils.telemetry import get_prometheus_text

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
