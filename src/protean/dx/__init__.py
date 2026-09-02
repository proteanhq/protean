"""Protean developer-experience (``dx``) substrate.

Homes the machinery the ``protean dx`` CLI group consumes. The
idempotent file-projection engine (:mod:`protean.dx.projection`) writes
agent-facing files into a user's project and can re-write them without clobbering
the user's own edits. The versioned pack (:mod:`protean.dx.pack`) is the
agent-facing knowledge those files carry, shipped as package data and read
through ``importlib.resources``. This package is internal substrate for the
``dx`` command stage; it is side-effect free on import and adds nothing to
top-level ``protean``.
"""

from __future__ import annotations

from protean.dx.pack import (
    AGENTS_SOURCE,
    PACK_VERSION,
    SKILL_FILE,
    SKILLS_DIR,
    diagnostic_code_skills,
    iter_skills,
    load_agents_source,
    pack_files,
    read_pack_text,
    skill_diagnostic_codes,
)
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
    "AGENTS_SOURCE",
    "LOCK_VERSION",
    "PACK_VERSION",
    "SKILLS_DIR",
    "SKILL_FILE",
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
    "diagnostic_code_skills",
    "diff_projection",
    "iter_skills",
    "load_agents_source",
    "load_lock",
    "pack_files",
    "read_pack_text",
    "skill_diagnostic_codes",
]
