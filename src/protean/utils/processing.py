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

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import IntEnum

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Message processing priority levels.

    A higher value means a higher priority, and the outbox publishes
    higher-priority messages first. When priority lanes are enabled, a value
    below ``server.priority_lanes.threshold`` (default 0) routes the event to
    the backfill lane, which the engine reads only when the primary lane is
    empty.

    Attributes:
        BULK: Bulk imports, re-indexing and mass data operations. Backfill lane.
        LOW: Background tasks, data migrations and non-urgent work. Backfill
            lane.
        NORMAL: The default for production traffic. Primary lane.
        HIGH: Time-sensitive operations. Primary lane.
        CRITICAL: System-critical operations such as payments. Primary lane.
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
def processing_priority(priority: Priority | int) -> Generator[None, None, None]:
    """Set the processing priority for every command processed inside the block.

    Events raised by those commands carry this priority. See ``Priority`` for
    how the value affects lane routing and outbox order.

    Contexts can be nested, and the innermost one wins. The previous priority
    is restored when the block exits, even when it raises.

    Args:
        priority: A ``Priority`` member or a plain integer.

    Example:
        >>> with processing_priority(Priority.LOW):
        ...     domain.process(CreateCustomer(name="Migration User"))
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
