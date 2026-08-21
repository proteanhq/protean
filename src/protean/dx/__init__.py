"""Protean developer-experience (``dx``) substrate.

Homes the machinery the ``protean dx`` CLI group consumes. It starts with the
idempotent file-projection engine (:mod:`protean.dx.projection`), which writes
agent-facing files into a user's project and can re-write them without clobbering
the user's own edits. This package is internal substrate for the ``dx`` command
stage; it is side-effect free on import and adds nothing to top-level
``protean``.
"""

from __future__ import annotations

from protean.dx.projection import (
    LOCK_VERSION,
    ManagedRegionProjection,
    Projection,
    ProjectionConflict,
    ProjectionEntry,
    ProjectionError,
    ProjectionLock,
    ProjectionMode,
    ProjectionResult,
    ProjectionStatus,
    StructuredJsonProjection,
    apply_projection,
    diff_projection,
    load_lock,
)

__all__ = [
    "LOCK_VERSION",
    "ManagedRegionProjection",
    "Projection",
    "ProjectionConflict",
    "ProjectionEntry",
    "ProjectionError",
    "ProjectionLock",
    "ProjectionMode",
    "ProjectionResult",
    "ProjectionStatus",
    "StructuredJsonProjection",
    "apply_projection",
    "diff_projection",
    "load_lock",
]
