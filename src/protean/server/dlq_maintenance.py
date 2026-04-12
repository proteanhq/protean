"""DLQ maintenance task for periodic trimming and alerting.

Runs as an async task inside the Engine, following the same lifecycle
pattern as OutboxProcessor.  It periodically:

1. Trims DLQ messages older than the configured retention period using
   ``BaseBroker.dlq_trim()``.
2. Checks DLQ depth against a threshold and logs a WARNING / calls an
   optional user-supplied callback when the threshold is exceeded.

Configuration lives in ``[server.dlq]`` within domain.toml, with
optional per-subscription overrides via ``dlq_retention_hours`` and
``dlq_alert_threshold`` on ``SubscriptionConfig``.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from typing import TYPE_CHECKING, Any, Callable

from protean.utils.dlq import discover_subscriptions
from protean.utils.telemetry import get_domain_metrics

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.server.engine import Engine

logger = logging.getLogger(__name__)


def _resolve_callback(dotted_path: str | None) -> Callable[..., Any] | None:
    """Import a callable from a dotted path like ``myapp.alerts.notify``."""
    if not dotted_path:
        return None
    module_path, _, attr_name = dotted_path.rpartition(".")
    if not module_path or not attr_name:
        logger.warning(
            "dlq.invalid_callback_path",
            extra={"path": dotted_path},
        )
        return None
    try:
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "dlq.callback_import_failed",
            extra={"path": dotted_path, "error": str(exc)},
        )
        return None


def _retention_hours_to_min_id(retention_hours: int) -> str:
    """Convert a retention window (hours) to a Redis stream MINID.

    Redis stream IDs are millisecond-epoch timestamps.  We compute the
    cutoff as ``now - retention_hours`` and format it so that XTRIM
    MINID removes everything strictly older.
    """
    cutoff_ms = int((time.time() - retention_hours * 3600) * 1000)
    return f"{cutoff_ms}-0"


class DLQMaintenanceTask:
    """Periodic DLQ trimming and alerting task.

    Attributes:
        engine: The Protean Engine instance.
        retention_hours: Global default retention in hours.
        alert_threshold: Global default DLQ depth alert threshold.
        alert_callback: Optional user callback invoked on threshold breach.
        check_interval: Seconds between maintenance cycles.
    """

    def __init__(self, engine: "Engine") -> None:
        self.engine = engine
        self.domain: "Domain" = engine.domain
        self.keep_going = True

        dlq_config = self.domain.config.get("server", {}).get("dlq", {})
        self.retention_hours: int = dlq_config.get("retention_hours", 168)
        self.alert_threshold: int = dlq_config.get("alert_threshold", 100)
        self.alert_callback = _resolve_callback(dlq_config.get("alert_callback"))
        self.check_interval: int = dlq_config.get("check_interval_seconds", 60)

        # Cache subscription info — subscriptions are immutable at runtime
        self._subscriptions = discover_subscriptions(self.domain)

        # Build per-subscription overrides from the engine's resolved configs
        self._per_sub_retention: dict[str, int] = {}
        self._per_sub_threshold: dict[str, int] = {}
        self._build_per_subscription_overrides()

    @property
    def subscriber_name(self) -> str:
        return "dlq-maintenance"

    def _build_per_subscription_overrides(self) -> None:
        """Cache per-subscription DLQ overrides for O(1) lookup during cycles.

        Subscriptions can override global ``[server.dlq]`` defaults via
        ``dlq_retention_hours`` / ``dlq_alert_threshold`` on their
        ``SubscriptionConfig``.  We index by DLQ stream name at init
        time rather than re-walking the engine on every cycle.
        """
        for _name, subscription in self.engine._subscriptions.items():
            config = getattr(subscription, "config", None)
            if config is None:
                continue
            dlq_stream = getattr(subscription, "dlq_stream", None)
            if dlq_stream is None:
                continue
            if config.dlq_retention_hours is not None:
                self._per_sub_retention[dlq_stream] = config.dlq_retention_hours
            if config.dlq_alert_threshold is not None:
                self._per_sub_threshold[dlq_stream] = config.dlq_alert_threshold

    async def start(self) -> None:
        """Start the maintenance loop."""
        logger.info("dlq_maintenance.started")
        self.engine.loop.create_task(self._run())

    async def _run(self) -> None:
        """Main loop: sleep, then run one maintenance cycle."""
        while self.keep_going and not self.engine.shutting_down:
            try:
                await asyncio.sleep(self.check_interval)
                if not self.keep_going or self.engine.shutting_down:
                    break
                await self._maintenance_cycle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("dlq_maintenance.cycle_failed")

    async def _maintenance_cycle(self) -> None:
        """Run one trim + alert pass across all DLQ streams."""
        broker = self._get_broker()
        if broker is None:
            return

        metrics = get_domain_metrics(self.domain)

        for sub_info in self._subscriptions:
            for dlq_stream in self._dlq_streams(sub_info):
                retention = self._per_sub_retention.get(
                    dlq_stream, self.retention_hours
                )
                threshold = self._per_sub_threshold.get(
                    dlq_stream, self.alert_threshold
                )

                # Trim + depth in a single thread call to minimize overhead
                min_id = _retention_hours_to_min_id(retention)
                trimmed, depth = await asyncio.to_thread(
                    self._trim_and_depth, broker, dlq_stream, min_id
                )
                if trimmed > 0:
                    metrics.dlq_trimmed.add(trimmed, {"dlq_stream": dlq_stream})

                if depth >= threshold:
                    logger.warning(
                        "dlq_maintenance.threshold_exceeded",
                        extra={
                            "dlq_stream": dlq_stream,
                            "depth": depth,
                            "threshold": threshold,
                        },
                    )
                    metrics.dlq_alerts.add(1, {"dlq_stream": dlq_stream})
                    self._invoke_callback(dlq_stream, depth, threshold)

    @staticmethod
    def _trim_and_depth(broker, dlq_stream: str, min_id: str) -> tuple[int, int]:
        """Run trim + depth in a single thread call."""
        trimmed = broker.dlq_trim(dlq_stream, min_id)
        depth = broker.dlq_depth(dlq_stream)
        return trimmed, depth

    def _get_broker(self):
        """Return the first broker that supports DLQ, or None."""
        from protean.port.broker import BrokerCapabilities

        for broker in self.domain.brokers.values():
            if broker.has_capability(BrokerCapabilities.DEAD_LETTER_QUEUE):
                return broker
        return None

    @staticmethod
    def _dlq_streams(sub_info) -> list[str]:
        """Return all DLQ stream names for a subscription."""
        streams = [sub_info.dlq_stream]
        if sub_info.backfill_dlq_stream:
            streams.append(sub_info.backfill_dlq_stream)
        return streams

    def _invoke_callback(self, dlq_stream: str, depth: int, threshold: int) -> None:
        """Call the user-supplied alert callback, if configured."""
        if self.alert_callback is None:
            return
        try:
            self.alert_callback(dlq_stream=dlq_stream, depth=depth, threshold=threshold)
        except Exception:
            logger.exception(
                "dlq_maintenance.callback_failed",
                extra={"dlq_stream": dlq_stream},
            )

    async def shutdown(self) -> None:
        """Signal the task to stop."""
        self.keep_going = False
        logger.info("dlq_maintenance.shutdown")
