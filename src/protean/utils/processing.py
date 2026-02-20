"""Processing context for priority-based event processing.

This module provides a priority system for controlling how events flow through
the async processing pipeline (outbox → broker → handlers). When priority lanes
are enabled, events tagged with low priority are routed to a separate "backfill"
Redis Stream, while normal/high priority events use the primary stream. The
Engine's StreamSubscription always drains the primary stream first, ensuring
production traffic is never held hostage by batch/migration work.

Usage:
    # Context manager for batch operations
    from protean.utils.processing import processing_priority, Priority

    with processing_priority(Priority.LOW):
        for item in migration_data:
            domain.process(CreateCustomer(**item))

    # Explicit priority per command
    domain.process(command, priority=Priority.LOW)

    # Nested contexts (inner overrides outer)
    with processing_priority(Priority.LOW):
        domain.process(cmd1)  # LOW
        with processing_priority(Priority.CRITICAL):
            domain.process(cmd2)  # CRITICAL
        domain.process(cmd3)  # LOW again
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from enum import IntEnum

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Message processing priority levels.

    Higher values = higher priority. Production traffic uses the default
    (NORMAL = 0). Migration and bulk operations should use LOW or BULK
    so their events are routed to the backfill lane when priority lanes
    are enabled.

    Attributes:
        BULK: For bulk imports, re-indexing, and mass data operations.
            Events are routed to the backfill lane and processed only
            when no higher-priority work is pending.
        LOW: For background tasks, data migrations, and non-urgent
            processing. Routed to backfill lane.
        NORMAL: The default for all production traffic. Events flow
            through the primary lane and are processed immediately.
        HIGH: For expedited processing of time-sensitive operations.
            Processed via the primary lane with outbox priority ordering.
        CRITICAL: For system-critical operations like payment processing
            or security-related events. Highest outbox priority.
    """

    BULK = -100
    LOW = -50
    NORMAL = 0
    HIGH = 50
    CRITICAL = 100


# Context variable for current processing priority.
# Using ContextVar (not threading.local) because it works correctly with
# asyncio — each async task gets its own copy, and values propagate
# through `await` chains automatically.
_processing_priority: ContextVar[int] = ContextVar(
    "processing_priority", default=Priority.NORMAL
)


@contextmanager
def processing_priority(priority):
    """Context manager to set processing priority for all operations in scope.

    All commands processed within this context will have their events tagged
    with the specified priority. When priority lanes are enabled, low-priority
    events (priority < threshold) are routed to the backfill Redis Stream
    and processed only when the primary stream is empty.

    Args:
        priority: A Priority enum member or integer value. Values below the
            configured threshold (default 0) are routed to the backfill lane.

    Yields:
        None

    Example:
        >>> with processing_priority(Priority.LOW):
        ...     domain.process(CreateCustomer(name="Migration User"))
        ...     # Events go to backfill lane

        >>> with processing_priority(Priority.CRITICAL):
        ...     domain.process(ProcessPayment(amount=100))
        ...     # Events get highest outbox priority

    Note:
        Contexts can be nested. The innermost context wins:

        >>> with processing_priority(Priority.LOW):
        ...     # priority is LOW here
        ...     with processing_priority(Priority.HIGH):
        ...         # priority is HIGH here
        ...     # priority is LOW again

        Priority is always restored after the context exits, even if an
        exception is raised within the block.
    """
    token = _processing_priority.set(int(priority))
    try:
        yield
    finally:
        _processing_priority.reset(token)


def current_priority() -> int:
    """Get the current processing priority from context.

    Returns the priority set by the nearest enclosing ``processing_priority()``
    context manager, or ``Priority.NORMAL`` (0) if no context is active.

    Returns:
        int: The current priority value.

    Example:
        >>> current_priority()
        0
        >>> with processing_priority(Priority.LOW):
        ...     current_priority()
        -50
    """
    return _processing_priority.get()
