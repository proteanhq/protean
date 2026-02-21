"""Projection rebuilding utilities.

Provides the orchestration logic for rebuilding projections by replaying
events from the event store through their associated projectors.

The rebuild process:

1. Discovers all projectors targeting a given projection class.
2. Truncates existing projection data (database rows or cache entries).
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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from protean.exceptions import ConfigurationError
from protean.utils import DomainObjects
from protean.utils.inflection import underscore

if TYPE_CHECKING:
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
    projection_cls: type,
    batch_size: int = 500,
) -> RebuildResult:
    """Rebuild a projection by replaying events through its projectors.

    Truncates existing projection data, then replays all events from the
    event store through each projector that targets this projection.
    Upcasters are applied automatically during replay.

    Events are read from the ``$all`` stream and filtered to only the
    categories each projector listens to, ensuring correct global ordering
    for cross-aggregate projections.

    Args:
        domain: The initialized domain instance.
        projection_cls: The projection class to rebuild.
        batch_size: Number of events to read per batch from the event store.

    Returns:
        RebuildResult with counts and any errors.
    """
    result = RebuildResult(projection_name=projection_cls.__name__)

    # Find all projectors for this projection
    projectors = domain.projectors_for(projection_cls)
    if not projectors:
        result.errors.append(
            f"No projectors found for projection `{projection_cls.__name__}`"
        )
        return result

    # Truncate projection data
    _truncate_projection(domain, projection_cls)
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
    """
    results: dict[str, RebuildResult] = {}

    for _, record in domain.registry._elements[DomainObjects.PROJECTION.value].items():
        if record.internal:
            continue
        result = rebuild_projection(domain, record.cls, batch_size)
        results[record.cls.__name__] = result

    return results


def _truncate_projection(domain: "Domain", projection_cls: type) -> None:
    """Truncate all data for a projection.

    Handles both database-backed and cache-backed projections.
    """
    if projection_cls.meta_.cache:
        cache = domain.cache_for(projection_cls)
        key_pattern = f"{underscore(projection_cls.__name__)}::*"
        cache.remove_by_key_pattern(key_pattern)
    else:
        repo = domain.repository_for(projection_cls)
        repo._dao._delete_all()


def _replay_projector(
    domain: "Domain",
    projector_cls: type,
    stream_categories: list[str],
    batch_size: int,
) -> tuple[int, int]:
    """Replay events through a projector in global order.

    Reads all events from each stream category, merges them by
    ``global_position``, and dispatches in chronological order.
    This ensures correct cross-aggregate ordering — e.g., a
    ``Registered`` event from the ``user`` category is always
    processed before a ``Transacted`` event from the ``transaction``
    category if that is the order in which they were originally stored.

    Args:
        domain: The initialized domain instance.
        projector_cls: The projector class to dispatch events through.
        stream_categories: Stream categories to include.
        batch_size: Number of events to read per batch per category.

    Returns:
        Tuple of (events_dispatched, events_skipped).
    """
    from protean.utils.eventing import Message

    logger.info(
        "Replaying categories %s through `%s`",
        stream_categories,
        projector_cls.__name__,
    )

    # Collect all messages from all categories.
    #
    # We read all events per category in a single call rather than
    # paginating, because the Memory event store's per-stream position
    # field doesn't support correct cross-stream pagination within a
    # category.  For production stores (MessageDB) a single large read
    # per category is equally efficient thanks to server-side cursors.
    all_messages: list[Message] = []
    for category in stream_categories:
        messages = domain.event_store.store.read(
            category,
            position=0,
            no_of_messages=1_000_000,
        )
        all_messages.extend(messages)

    # Sort by global_position for correct cross-category ordering
    all_messages.sort(key=lambda m: (m.metadata.event_store.global_position or 0))

    dispatched = 0
    skipped = 0

    for message in all_messages:
        try:
            projector_cls._handle(message)
            dispatched += 1
        except ConfigurationError as exc:
            # Unresolvable event type (deprecated event without upcaster)
            logger.warning(
                "Skipping unresolvable message type `%s` at position %s: %s",
                message.metadata.headers.type
                if message.metadata.headers
                else "unknown",
                message.metadata.event_store.global_position
                if message.metadata.event_store
                else "unknown",
                exc,
            )
            skipped += 1
        except Exception as exc:
            logger.warning(
                "Error processing message at position %s: %s",
                message.metadata.event_store.global_position
                if message.metadata.event_store
                else "unknown",
                exc,
            )
            skipped += 1

    logger.info(
        "Replayed %d events (%d skipped) from %s through `%s`",
        dispatched,
        skipped,
        stream_categories,
        projector_cls.__name__,
    )

    return dispatched, skipped
