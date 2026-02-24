"""DLQ discovery utility.

Walks the domain registry to enumerate subscriptions and derive their
associated DLQ stream names. This avoids Redis keyspace scanning and
keeps the mapping consistent with how the Engine creates subscriptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from protean.utils import DomainObjects

if TYPE_CHECKING:
    from protean.domain import Domain


@dataclass
class SubscriptionInfo:
    """Describes a handler subscription and its DLQ stream(s)."""

    handler_name: str
    handler_fqn: str
    stream_category: str
    dlq_stream: str
    backfill_dlq_stream: str | None


def _infer_stream_category(handler_cls: type) -> str | None:
    """Infer stream category from a handler class.

    Mirrors ``Engine._infer_stream_category`` resolution order:
    1. Explicit ``meta_.stream_category``
    2. Aggregate's ``meta_.stream_category`` via ``part_of``
    """
    meta = getattr(handler_cls, "meta_", None)
    if meta is None:
        return None

    stream_category = getattr(meta, "stream_category", None)
    if stream_category:
        return stream_category

    part_of = getattr(meta, "part_of", None)
    if part_of:
        aggregate_meta = getattr(part_of, "meta_", None)
        if aggregate_meta:
            return getattr(aggregate_meta, "stream_category", None)

    return None


def discover_subscriptions(domain: "Domain") -> list[SubscriptionInfo]:
    """Walk the domain registry and return subscription metadata.

    Inspects event handlers, command handlers, and projectors to derive
    their stream categories and DLQ stream names.
    """
    from protean.utils import fqn

    server_config = domain.config.get("server", {})
    lanes_config = server_config.get("priority_lanes", {})
    lanes_enabled = lanes_config.get("enabled", False)
    backfill_suffix = lanes_config.get("backfill_suffix", "backfill")

    seen_streams: dict[str, SubscriptionInfo] = {}
    infos: list[SubscriptionInfo] = []

    def _add(handler_cls: type, stream_cat: str) -> None:
        key = f"{fqn(handler_cls)}:{stream_cat}"
        if key in seen_streams:
            return

        backfill_dlq = f"{stream_cat}:{backfill_suffix}:dlq" if lanes_enabled else None
        info = SubscriptionInfo(
            handler_name=handler_cls.__name__,
            handler_fqn=fqn(handler_cls),
            stream_category=stream_cat,
            dlq_stream=f"{stream_cat}:dlq",
            backfill_dlq_stream=backfill_dlq,
        )
        seen_streams[key] = info
        infos.append(info)

    # Event handlers
    for _, record in domain.registry._elements.get(
        DomainObjects.EVENT_HANDLER.value, {}
    ).items():
        handler_cls = record.cls
        stream_cat = _infer_stream_category(handler_cls)
        if stream_cat:
            _add(handler_cls, stream_cat)

    # Command handlers
    for _, record in domain.registry._elements.get(
        DomainObjects.COMMAND_HANDLER.value, {}
    ).items():
        handler_cls = record.cls
        stream_cat = _infer_stream_category(handler_cls)
        if stream_cat:
            _add(handler_cls, stream_cat)

    # Projectors (may subscribe to multiple stream categories)
    for _, record in domain.registry._elements.get(
        DomainObjects.PROJECTOR.value, {}
    ).items():
        handler_cls = record.cls
        stream_categories = getattr(
            getattr(handler_cls, "meta_", None), "stream_categories", None
        )
        if stream_categories:
            for stream_cat in stream_categories:
                _add(handler_cls, stream_cat)

    return infos


def collect_dlq_streams(domain: "Domain") -> list[str]:
    """Return a flat list of all DLQ stream names for the domain."""
    streams: list[str] = []
    for info in discover_subscriptions(domain):
        streams.append(info.dlq_stream)
        if info.backfill_dlq_stream:
            streams.append(info.backfill_dlq_stream)
    # Deduplicate while preserving order
    return list(dict.fromkeys(streams))
