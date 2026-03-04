"""Prometheus metrics endpoint for the Protean Observatory.

Exposes metrics in Prometheus text exposition format, suitable for scraping
by Prometheus or any compatible monitoring system. No external dependencies —
uses hand-rolled text format to keep Protean lean.

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
"""

import logging
from typing import List

from fastapi import Response

from protean.domain import Domain

logger = logging.getLogger(__name__)


def create_metrics_endpoint(domains: List[Domain]):
    """Create the Prometheus metrics endpoint function."""

    async def metrics():
        """Prometheus text exposition format metrics.

        Returns all Observatory metrics in Prometheus text format, suitable
        for scraping by Prometheus, Grafana Agent, or any compatible collector.

        Example:
        ```
        protean_outbox_messages{domain="identity",status="PENDING"} 3
        protean_redis_up 1
        protean_stream_messages_total 2139
        ```
        """
        lines = []

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

                    # Broker health
                    lines.append("")
                    lines.append(
                        "# HELP protean_broker_up Broker health (1=up, 0=down)"
                    )
                    lines.append("# TYPE protean_broker_up gauge")
                    lines.append(
                        f"protean_broker_up {1 if is_connected and details.get('healthy') else 0}"
                    )

                    # Broker memory
                    lines.append("")
                    lines.append(
                        "# HELP protean_broker_memory_bytes Broker memory usage in bytes"
                    )
                    lines.append("# TYPE protean_broker_memory_bytes gauge")
                    lines.append(
                        f"protean_broker_memory_bytes {details.get('used_memory', 0)}"
                    )

                    # Broker clients
                    lines.append("")
                    lines.append(
                        "# HELP protean_broker_connected_clients Number of connected broker clients"
                    )
                    lines.append("# TYPE protean_broker_connected_clients gauge")
                    lines.append(
                        f"protean_broker_connected_clients {details.get('connected_clients', 0)}"
                    )

                    # Broker ops/sec
                    lines.append("")
                    lines.append(
                        "# HELP protean_broker_ops_per_sec Broker operations per second"
                    )
                    lines.append("# TYPE protean_broker_ops_per_sec gauge")
                    lines.append(
                        f"protean_broker_ops_per_sec {details.get('instantaneous_ops_per_sec', 0)}"
                    )

                    # Stream message counts
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

                    # Stream count
                    streams_info = details.get("streams", {})
                    lines.append("")
                    lines.append(
                        "# HELP protean_streams_count Number of active streams"
                    )
                    lines.append("# TYPE protean_streams_count gauge")
                    lines.append(
                        f"protean_streams_count {streams_info.get('count', 0)}"
                    )

                    # Consumer group count
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
        return Response(
            content="\n".join(lines),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return metrics
