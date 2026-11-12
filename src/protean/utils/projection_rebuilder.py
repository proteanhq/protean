"""Projection rebuilding utilities.

Provides the orchestration logic for rebuilding projections by replaying
events from the event store through their associated projectors.

The rebuild process:

1. Discovers all projectors targeting a given projection class.
2. Truncates existing projection data (database rows or cache entries).
   For a database-backed projection, the same unit of work also deletes the
   delivery markers of its idempotent projectors, so the replay is not
   skipped as a redelivery and writes fresh markers. On a relational or
   in-memory provider a failed marker delete rolls back the row delete;
   Elasticsearch has no transactions, so it gives no such rollback.
3. Reads events from each projector's stream categories, merges them by
   ``global_position`` for correct cross-aggregate ordering, and dispatches
   each event through the projector's ``_handle()`` method.

Upcasters are applied automatically during replay via ``to_domain_object()``.
Events whose type cannot be resolved (deprecated events without an upcaster
chain) are caught, logged, and skipped.

The rebuild is **idempotent** -- running it again truncates and replays from
scratch with no checkpointing or partial state.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.port.cache import CacheCapabilities
from protean.utils import DomainObjects, fqn
from protean.utils.eventing import Message
from protean.utils.query import Q
from protean.utils.telemetry import describe_exception

if TYPE_CHECKING:
    from protean.core.projection import BaseProjection
    from protean.core.projector import BaseProjector
    from protean.domain import Domain

logger = logging.getLogger(__name__)


@dataclass
class RebuildResult:
    """Result of a projection rebuild operation.

    Attributes:
        projection_name: Name of the projection class that was rebuilt.
        projectors_processed: Number of projectors that were run.
        categories_processed: Total stream categories read across all projectors.
        events_dispatched: Number of events successfully processed by handlers.
        events_skipped: Number of events that could not be resolved or failed
            during handler execution.
        errors: Error messages (empty on success). Non-empty errors cause
            ``success`` to return ``False``.
    """

    projection_name: str
    projectors_processed: int = 0
    categories_processed: int = 0
    events_dispatched: int = 0
    events_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Return ``True`` when the rebuild completed without errors."""
        return len(self.errors) == 0


def rebuild_projection(
    domain: "Domain",
    projection_cls: "type[BaseProjection]",
    batch_size: int = 500,
) -> RebuildResult:
    """Rebuild a projection by replaying events through its projectors.

    Truncates existing projection data, then replays all events from the
    event store through each projector that targets this projection.

    An event that cannot be resolved or whose handler raises is logged and
    counted in ``events_skipped``; the rebuild continues. An error while
    reading events from the store is raised, after the projection has been
    truncated. A projection with no
    projectors is not truncated, and the result carries an error.

    For a database-backed projection, the truncate also deletes the delivery
    markers of every idempotent projector targeting it, in the same
    transaction as the row delete. The replay then writes fresh markers.

    Must be called after ``domain.init()`` and within
    ``domain.domain_context()``.

    Args:
        domain: The initialized domain instance.
        projection_cls: The projection class to rebuild.
        batch_size: Number of events to read per batch from the event store.

    Returns:
        RebuildResult with counts and any errors.

    Raises:
        NotSupportedError: The projection is cache-backed and its cache does
            not support ``CacheCapabilities.PATTERN_MATCH``. It is raised
            before any event is replayed.
    """
    result = RebuildResult(projection_name=projection_cls.__name__)

    # Find all projectors for this projection
    projectors = domain.projectors_for(projection_cls)
    if not projectors:
        result.errors.append(
            f"No projectors found for projection `{projection_cls.__name__}`"
        )
        return result

    _check_truncatable(domain, projection_cls)

    # Truncate projection data
    _truncate_projection(domain, projection_cls, projectors)
    logger.info("Truncated projection `%s`", projection_cls.__name__)

    # Replay events through each projector
    for projector_cls in projectors:
        result.projectors_processed += 1
        categories = list(projector_cls.meta_.stream_categories)
        result.categories_processed += len(categories)

        dispatched, skipped = _replay_projector(
            domain, projector_cls, categories, batch_size
        )
        result.events_dispatched += dispatched
        result.events_skipped += skipped

    logger.info(
        "Rebuilt projection `%s`: %d events dispatched, %d skipped, "
        "%d projector(s), %d category/categories",
        projection_cls.__name__,
        result.events_dispatched,
        result.events_skipped,
        result.projectors_processed,
        result.categories_processed,
    )

    return result


def rebuild_all_projections(
    domain: "Domain",
    batch_size: int = 500,
) -> dict[str, RebuildResult]:
    """Rebuild all projections registered in the domain.

    Args:
        domain: The initialized domain instance.
        batch_size: Number of events to read per batch from the event store.

    Returns:
        Dictionary mapping projection class names to their RebuildResult.

    Raises:
        NotSupportedError: A cache-backed projection's cache does not support
            ``CacheCapabilities.PATTERN_MATCH``. It is raised before any
            projection is truncated or any event is replayed.
    """
    projection_classes = [
        record.cls
        for record in domain.registry._elements[DomainObjects.PROJECTION.value].values()
        if not record.internal
    ]
    for projection_cls in projection_classes:
        if domain.projectors_for(projection_cls):
            _check_truncatable(domain, projection_cls)

    return {
        projection_cls.__name__: rebuild_projection(domain, projection_cls, batch_size)
        for projection_cls in projection_classes
    }


def _check_truncatable(
    domain: "Domain", projection_cls: "type[BaseProjection]"
) -> None:
    """Raise ``NotSupportedError`` if the projection's entries cannot be removed.

    A cache-backed projection is truncated with a key pattern, so its cache
    must support ``CacheCapabilities.PATTERN_MATCH``.
    """
    if not projection_cls.meta_.cache:
        return
    cache = domain.cache_for(projection_cls)
    if CacheCapabilities.PATTERN_MATCH not in cache.capabilities:
        raise NotSupportedError(
            f"Cache '{cache.name}' does not support "
            f"CacheCapabilities.PATTERN_MATCH, which rebuilding projection "
            f"`{projection_cls.__name__}` needs."
        )


def _truncate_projection(
    domain: "Domain",
    projection_cls: "type[BaseProjection]",
    projectors: "Iterable[type[BaseProjector]]",
) -> None:
    """Truncate all data for a projection.

    Handles both database-backed and cache-backed projections. For a
    database-backed projection, also deletes the delivery markers of the
    idempotent projectors in ``projectors``, in one transaction with the rows.
    """
    if projection_cls.meta_.cache:
        cache = domain.cache_for(projection_cls)
        cache.remove_by_key_pattern(cache.pattern_for(projection_cls))
        return

    # A marker left behind makes the replay skip its event as an
    # already-processed redelivery, so the truncated projection stays empty.
    # The ids must match what dispatch writes: ``fqn`` of each handler method.
    handler_ids = sorted(
        {
            fqn(cast(Any, method))
            for projector_cls in projectors
            if projector_cls.meta_.idempotent
            for methods in projector_cls._handlers.values()
            for method in methods
        }
    )

    marker_repo = None
    if handler_ids:
        provider_name = projection_cls.meta_.provider
        try:
            marker_repo = domain._get_processed_message_repo(provider_name)
        except KeyError:
            # Same fallback as dispatch: this provider has no marker store.
            marker_repo = None

    repo = domain.repository_for(projection_cls)
    # Rows first, markers second, in one unit of work: on a provider with
    # transactions (relational, memory) a failed marker delete rolls back the
    # row delete, so a failed rebuild leaves the projection as it was instead
    # of empty with its markers still in place. Elasticsearch has no
    # transactions and writes each delete at once, so it gets no rollback.
    with UnitOfWork():
        repo._dao._delete_all()
        if marker_repo is not None:
            marker_repo._dao._delete_all(Q(handler__in=handler_ids))


def _global_position(message: Message) -> int:
    """Return the store's ``global_position`` of *message*, or 0 when it has
    none."""
    # Defensive: event-store messages always carry metadata/event_store;
    # this guards only against corrupt store data.
    if (
        message.metadata is None or message.metadata.event_store is None
    ):  # pragma: no cover
        return 0
    return message.metadata.event_store.global_position or 0


def _position_label(message: Message) -> object:
    """Return the ``global_position`` of *message* for a log line, or
    ``"unknown"`` when it has no event store metadata."""
    return (
        message.metadata.event_store.global_position
        if message.metadata and message.metadata.event_store
        else "unknown"
    )


def _dispatch_message(projector_cls: "type[BaseProjector]", message: Message) -> bool:
    """Dispatch *message* through *projector_cls*.

    Returns True when the projector handled it. Returns False and logs the
    error when dispatch raised, so the caller counts the message as skipped.
    """
    try:
        projector_cls._handle(message)
        return True
    except ConfigurationError as exc:
        # Unresolvable event type (deprecated event without upcaster)
        logger.warning(
            "Skipping unresolvable message type `%s` at position %s: %s",
            message.metadata.headers.type
            if message.metadata and message.metadata.headers
            else "unknown",
            _position_label(message),
            exc,
        )
        return False
    except Exception as exc:
        # `exc_info` matters more than it looks: a skipped message means the
        # projection is wrong, and `str()` of an exception group names none
        # of its members, so without the traceback there is nothing to act on.
        logger.error(
            "Error processing message at position %s: %s",
            _position_label(message),
            describe_exception(exc),
            exc_info=exc,
        )
        return False


def _replay_projector(
    domain: "Domain",
    projector_cls: "type[BaseProjector]",
    stream_categories: list[str],
    batch_size: int,
) -> tuple[int, int]:
    """Replay every event in ``stream_categories`` through a projector.

    Events from all categories are dispatched in the order the store wrote
    them (``global_position``). A message that fails to dispatch is logged and
    counted as skipped. An error while reading events from the store is
    raised.

    Args:
        domain: The initialized domain instance.
        projector_cls: The projector class to dispatch events through.
        stream_categories: Stream categories to include.
        batch_size: Number of events to read per batch per category.

    Returns:
        Tuple of (events_dispatched, events_skipped).
    """
    logger.info(
        "Replaying categories %s through `%s`",
        stream_categories,
        projector_cls.__name__,
    )

    # Collect all messages from all categories.
    #
    # A full rebuild replays every event in a category, so we page through the
    # whole category with `read_all`. A category larger than the read cap is not
    # silently truncated. `batch_size` sets the page size, so each round-trip to
    # the store is bounded; peak memory is still O(all events), since the merge
    # below collects every message into one list to sort by `global_position`.
    all_messages: list[Message] = []
    event_store = domain._require_event_store()
    for category in stream_categories:
        all_messages.extend(event_store.read_all(category, page_size=batch_size))

    # Sort by global_position for correct cross-category ordering
    all_messages.sort(key=_global_position)

    dispatched = 0
    skipped = 0

    for message in all_messages:
        if _dispatch_message(projector_cls, message):
            dispatched += 1
        else:
            skipped += 1

    logger.info(
        "Replayed %d events (%d skipped) from %s through `%s`",
        dispatched,
        skipped,
        stream_categories,
        projector_cls.__name__,
    )

    return dispatched, skipped
