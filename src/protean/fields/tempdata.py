"""Typed change-tracking classes for association field _temp_cache.

These classes replace the untyped ``defaultdict(lambda: defaultdict(dict))``
that was previously used to track pending child entity changes on aggregates
and entities.

``HasManyChanges`` tracks individual items added, updated, or removed from
a one-to-many association.  ``HasOneChanges`` tracks the relationship state
(ADDED / UPDATED / DELETED) for a one-to-one association.

``AssociationCache`` is the top-level container keyed by field name.
Association fields create their entries explicitly via ``setdefault()``.
"""

from __future__ import annotations

from typing import Any


class HasManyChanges:
    """Track pending child entity changes for a HasMany association field.

    Each dict is keyed by the child entity's identity value.
    """

    __slots__ = ("added", "updated", "removed")

    def __init__(self) -> None:
        self.added: dict[Any, Any] = {}
        self.updated: dict[Any, Any] = {}
        self.removed: dict[Any, Any] = {}

    def clear(self) -> None:
        """Reset all tracked changes."""
        self.added = {}
        self.updated = {}
        self.removed = {}


class HasOneChanges:
    """Track pending relationship state for a HasOne association field.

    ``change`` records the nature of the mutation:
    - ``"ADDED"``   — a child was associated for the first time
    - ``"UPDATED"`` — the associated child was replaced or modified
    - ``"DELETED"`` — the association was removed
    - ``None``      — no pending change (no-op assignment)

    ``old_value`` holds the previous entity when the reference was replaced
    or deleted, so the repository can clean up the old record.
    """

    __slots__ = ("change", "old_value")

    def __init__(self) -> None:
        self.change: str | None = None
        self.old_value: Any = None

    def clear(self) -> None:
        """Reset tracked change state."""
        self.change = None
        self.old_value = None


class AssociationCache(dict[str, HasManyChanges | HasOneChanges]):
    """Container for association field change tracking.

    A plain ``dict`` subclass keyed by field name.  Association fields
    create their entries lazily via ``setdefault()`` with the appropriate
    change-tracker type (``HasManyChanges`` or ``HasOneChanges``).
    """

    pass
