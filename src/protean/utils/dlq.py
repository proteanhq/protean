"""DLQ discovery utility.

Walks the domain registry to enumerate subscriptions and derive their
associated DLQ stream names. This avoids Redis keyspace scanning and
keeps the mapping consistent with how the Engine creates subscriptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from protean.utils import DomainObjects, fqn

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
    is_broker: bool = False
    is_command_handler: bool = False

    @property
    def subscription_fqn(self) -> str:
        """The fqn of the subscription that owns this handler's failed stream.

        The engine fans every command handler on a stream category into one
        ``CommandDispatcher`` subscription, so the failed-positions stream is
        keyed by the dispatcher's fqn, not the handler class. Event handlers and
        projectors own their stream directly, so it is their own fqn. Reads use
        this both to key the stream and to name the subscription in CLI output,
        so the two never diverge.
        """
        if self.is_command_handler:
            return command_dispatcher_fqn(self.stream_category)
        return self.handler_fqn


# Module and name the engine gives the CommandDispatcher it wraps a command
# stream's handlers in. The dispatcher lives in ``protean.server.engine``; that
# module imports the two helpers below to build its identity, so the name the
# subscription writes to and the name the CLI reads from stay one string.
COMMAND_DISPATCHER_MODULE = "protean.server.engine"


def command_dispatcher_name(stream_category: str) -> str:
    """Return the CommandDispatcher's short name for a command stream category."""
    return f"Commands:{stream_category}"


def command_dispatcher_fqn(stream_category: str) -> str:
    """Return the fully qualified name of the CommandDispatcher for a stream.

    The engine fans every command handler on a stream category into one
    ``CommandDispatcher`` subscription, so that subscription's failed-positions
    stream is keyed by the dispatcher's ``fqn``, not by any single handler
    class. ``collect_failed_streams`` uses this so the CLI reads the same stream
    the subscription writes to.
    """
    return f"{COMMAND_DISPATCHER_MODULE}.{command_dispatcher_name(stream_category)}"


def failed_positions_stream(handler_fqn: str, stream_category: str) -> str:
    """Return the event-store failed-positions stream name for a subscription.

    This is the single source of the name the ``EventStoreSubscription`` writes
    its ``Failed``/``Exhausted`` records to (see the subscription's
    ``failed_positions_stream`` attribute). The CLI and the subscription both
    call this so the name cannot drift between the writer and the reader.
    """
    return f"failed-{handler_fqn}-{stream_category}"


def _infer_stream_category(handler_cls: type) -> str | None:
    """Infer stream category from a handler class.

    Mirrors ``Engine._infer_stream_category`` resolution order:
    1. Explicit ``meta_.stream_category``
    2. Aggregate's ``meta_.stream_category`` via ``part_of``
    """
    meta = getattr(handler_cls, "meta_", None)
    if meta is None:
        return None

    stream_category: str | None = getattr(meta, "stream_category", None)
    if stream_category:
        return stream_category

    part_of = getattr(meta, "part_of", None)
    if part_of:
        aggregate_meta = getattr(part_of, "meta_", None)
        if aggregate_meta:
            return getattr(aggregate_meta, "stream_category", None)

    return None


def discover_subscriptions(domain: Domain) -> list[SubscriptionInfo]:
    """Walk the domain registry and return subscription metadata.

    Inspects event handlers, command handlers, and projectors to derive
    their stream categories and DLQ stream names.
    """
    server_config = domain.config.get("server", {})
    lanes_config = server_config.get("priority_lanes", {})
    lanes_enabled = lanes_config.get("enabled", False)
    backfill_suffix = lanes_config.get("backfill_suffix", "backfill")

    seen_streams: dict[str, SubscriptionInfo] = {}
    infos: list[SubscriptionInfo] = []

    def _add(
        handler_cls: type, stream_cat: str, *, is_command_handler: bool = False
    ) -> None:
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
            is_command_handler=is_command_handler,
        )
        seen_streams[key] = info
        infos.append(info)

    # Event handlers
    for record in domain.registry._elements.get(
        DomainObjects.EVENT_HANDLER.value, {}
    ).values():
        handler_cls = record.cls
        stream_cat = _infer_stream_category(handler_cls)
        if stream_cat:
            _add(handler_cls, stream_cat)

    # Command handlers
    for record in domain.registry._elements.get(
        DomainObjects.COMMAND_HANDLER.value, {}
    ).values():
        handler_cls = record.cls
        stream_cat = _infer_stream_category(handler_cls)
        if stream_cat:
            _add(handler_cls, stream_cat, is_command_handler=True)

    # Projectors (may subscribe to multiple stream categories)
    for record in domain.registry._elements.get(
        DomainObjects.PROJECTOR.value, {}
    ).values():
        handler_cls = record.cls
        stream_categories = getattr(
            getattr(handler_cls, "meta_", None), "stream_categories", None
        )
        if stream_categories:
            for stream_cat in stream_categories:
                _add(handler_cls, stream_cat)

    # Subscribers (broker subscriptions with external streams)
    for record in domain.registry._elements.get(
        DomainObjects.SUBSCRIBER.value, {}
    ).values():
        handler_cls = record.cls
        meta = getattr(handler_cls, "meta_", None)
        stream = getattr(meta, "stream", None) if meta else None
        if stream:
            key = f"{fqn(handler_cls)}:{stream}"
            if key not in seen_streams:
                info = SubscriptionInfo(
                    handler_name=handler_cls.__name__,
                    handler_fqn=fqn(handler_cls),
                    stream_category=stream,
                    dlq_stream=f"{stream}:dlq",
                    backfill_dlq_stream=None,  # Broker subscriptions don't use priority lanes
                    is_broker=True,
                )
                seen_streams[key] = info
                infos.append(info)

    return infos


def collect_dlq_streams(domain: Domain) -> list[str]:
    """Return a flat list of all DLQ stream names for the domain."""
    streams: list[str] = []
    for info in discover_subscriptions(domain):
        streams.append(info.dlq_stream)
        if info.backfill_dlq_stream:
            streams.append(info.backfill_dlq_stream)
    # Deduplicate while preserving order
    return list(dict.fromkeys(streams))


def collect_failed_streams(domain: Domain) -> list[tuple[SubscriptionInfo, str]]:
    """Return each event-store subscription paired with its failed-positions stream.

    Only event-store subscriptions (event handlers, command handlers, projectors)
    have a failed-positions stream; broker subscribers do not, so they are
    excluded. A projector subscribing to several stream categories yields one
    pair per category, matching how the engine creates one subscription per
    (handler, category).

    Command handlers are the exception: the engine fans every command handler on
    a stream category into a single ``CommandDispatcher`` subscription, so their
    failed-positions stream is keyed by the dispatcher's name, not the handler
    class. Those handlers therefore collapse to one pair per stream category,
    keyed by ``command_dispatcher_fqn`` so the CLI reads the stream the
    subscription actually wrote to.
    """
    pairs: list[tuple[SubscriptionInfo, str]] = []
    seen: set[str] = set()
    for info in discover_subscriptions(domain):
        if info.is_broker:
            continue
        failed_stream = failed_positions_stream(
            info.subscription_fqn, info.stream_category
        )
        if failed_stream in seen:
            continue
        seen.add(failed_stream)
        pairs.append((info, failed_stream))
    return pairs
