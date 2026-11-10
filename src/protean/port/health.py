"""Records that the health members of the adapter Ports share."""

from typing import TypedDict


class PoolStats(TypedDict):
    """The state of an adapter's connection pool.

    The event-store, cache and provider health records carry one of these, or
    `None` for an adapter without a pool.
    """

    size: int
    """Connections the pool holds open, idle or in use."""

    checked_out: int
    """Connections a caller is using now."""

    overflow: int
    """Connections opened past `size`, up to the pool's overflow limit."""

    checked_in: int
    """Idle connections waiting in the pool."""
