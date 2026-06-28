"""Projection staleness monitoring for Protean applications.

Projections (read models) are the unit operators reason about — "is my
``OrderSummary`` up to date?" — but a single projection can be fed by several
projectors, each subscribing to one or more stream categories. This module
aggregates those per-projector subscription positions into one projection-centric
view: how far behind the read model is in *time* (staleness) and in *events* (lag),
plus its current row count.

It reuses the same position data as :mod:`protean.server.subscription_status`
(the single source of truth for position/lag), grouped by the projection each
projector writes to.

Usage::

    from protean.server.projection_status import collect_projection_statuses

    for p in collect_projection_statuses(domain):
        print(f"{p.projection_name}: stale={p.staleness_seconds}s, lag={p.lag}")
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from protean.server.subscription.config_resolver import ConfigResolver
from protean.server.subscription.profiles import SubscriptionType

# Internal reuse: these helpers read the position stream / consumer group for a
# single subscription and already populate ``lag`` and ``last_updated``. The
# projection view groups their results by target projection.
from protean.server.subscription_status import (
    SubscriptionStatus,
    _classify_status,
    _collect_event_store_status,
    _collect_stream_status,
)
from protean.utils import ensure_utc_aware

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProjectionStatus:
    """Staleness snapshot for a single projection (read model)."""

    projection_name: str
    """The projection class name (e.g. ``"OrderSummary"``)."""

    projectors: list[str]
    """Names of the projectors that feed this projection."""

    last_updated: str | None
    """ISO timestamp the projection last advanced (most recent feeder), or ``None``."""

    staleness_seconds: float | None
    """Seconds behind: ``0`` when caught up, time-since-last-update when lagging,
    ``None`` when unknown or never updated."""

    lag: int | None
    """Events behind head — the worst (max) across feeders. ``None`` when unavailable."""

    row_count: int | None
    """Rows currently in the projection store, or ``None`` when uncountable."""

    status: str
    """``"ok"`` | ``"lagging"`` | ``"unknown"``."""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public collection function
# ---------------------------------------------------------------------------


def collect_projection_statuses(
    domain: Domain, *, include_row_count: bool = True
) -> list[ProjectionStatus]:
    """Collect a staleness snapshot for every projection in a domain.

    Walks the registry to map projectors to the projection each writes to, reads
    each projector subscription's position, and aggregates per projection. Does
    **not** require the Engine to be running.

    Args:
        domain: An initialised Protean domain.
        include_row_count: When ``False``, skip the per-projection row ``COUNT``
            query. The metrics scrape path passes ``False`` since it only reads
            staleness; the CLI leaves it ``True`` to show row counts.

    Returns:
        One :class:`ProjectionStatus` per registered projection.
    """
    statuses: list[ProjectionStatus] = []
    config_resolver = ConfigResolver(domain)
    now = datetime.now(timezone.utc)

    for _, record in domain.registry.projections.items():
        projection_cls = record.cls
        feeders = _feeder_statuses(domain, projection_cls, config_resolver)
        projectors = sorted({f.handler_name for f in feeders})
        row_count = _row_count(domain, projection_cls) if include_row_count else None
        statuses.append(_aggregate(projection_cls, feeders, projectors, now, row_count))

    return statuses


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feeder_statuses(
    domain: Domain,
    projection_cls: type,
    config_resolver: ConfigResolver,
) -> list[SubscriptionStatus]:
    """Collect the subscription status of every projector feeding a projection."""
    feeders: list[SubscriptionStatus] = []

    for projector_name, record in domain.registry.projectors.items():
        projector_cls = record.cls
        if projector_cls.meta_.projector_for is not projection_cls:
            continue

        for stream_category in projector_cls.meta_.stream_categories:
            sub_name = f"{projector_name}-{stream_category}"
            config = config_resolver.resolve(
                projector_cls, stream_category=stream_category
            )
            if config.subscription_type == SubscriptionType.EVENT_STORE:
                feeders.append(
                    _collect_event_store_status(
                        domain, sub_name, projector_cls, stream_category
                    )
                )
            else:
                feeders.append(
                    _collect_stream_status(
                        domain, sub_name, projector_cls, stream_category
                    )
                )

    return feeders


def _aggregate(
    projection_cls: type,
    feeders: list[SubscriptionStatus],
    projectors: list[str],
    now: datetime,
    row_count: int | None,
) -> ProjectionStatus:
    """Fold per-feeder statuses into one projection-centric snapshot (pure)."""
    lags = [f.lag for f in feeders if f.lag is not None]
    lag = max(lags) if lags else None

    # Parse each feeder's last-updated once; reuse for both the display
    # timestamp and the staleness computation.
    parsed = [(f, _parse_time(f.last_updated)) for f in feeders]
    times = [t for _, t in parsed if t is not None]
    last_updated = max(times) if times else None

    # Per-feeder staleness: caught-up feeders contribute 0; lagging feeders
    # contribute time-since-their-last-update; unknown/never-updated contribute
    # nothing. The projection is as stale as its worst feeder.
    stale_values: list[float] = []
    for feeder, feeder_time in parsed:
        if feeder.lag is None:
            continue
        if feeder.lag == 0:
            stale_values.append(0.0)
            continue
        if feeder_time is not None:
            # Clamp clock skew (position timestamp slightly ahead of now) to 0.
            stale_values.append(max(0.0, (now - feeder_time).total_seconds()))
    staleness_seconds = max(stale_values) if stale_values else None

    status = _classify_status(lag)

    return ProjectionStatus(
        projection_name=projection_cls.__name__,
        projectors=projectors,
        last_updated=last_updated.isoformat() if last_updated else None,
        staleness_seconds=staleness_seconds,
        lag=lag,
        row_count=row_count,
        status=status,
    )


def _row_count(domain: Domain, projection_cls: type) -> int | None:
    """Count rows in a projection's store, or ``None`` if uncountable (e.g. cache)."""
    try:
        with domain.domain_context():
            return domain.repository_for(projection_cls).query.count()
    except Exception as exc:
        logger.debug(
            "Could not count rows for projection %s: %s",
            projection_cls.__name__,
            exc,
        )
        return None


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
