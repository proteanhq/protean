"""Protean developer-experience (``dx``) substrate.

Homes the machinery the ``protean dx`` CLI group consumes. The idempotent
managed-file writer (:mod:`protean.dx.managed_files`) generates agent-facing
files into a user's project and can re-write them without clobbering the user's
own edits. The versioned pack (:mod:`protean.dx.pack`) is the agent-facing
knowledge those files carry, shipped as package data and read through
``importlib.resources``. This package is internal substrate for the ``dx``
command stage; it is side-effect free on import and adds nothing to top-level
``protean``.
"""

from __future__ import annotations

from protean.dx.managed_files import (
    STATE_VERSION,
    ApplyResult,
    ApplyStatus,
    FileStateEntry,
    ManagedBlock,
    ManagedFile,
    ManagedFileConflict,
    ManagedFileError,
    ManagedFileState,
    ManagedJsonKeys,
    MergeMode,
    apply_managed_file,
    diff_managed_file,
    load_state,
)
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

__all__ = [
    "AGENTS_SOURCE",
    "PACK_VERSION",
    "SKILLS_DIR",
    "SKILL_FILE",
    "STATE_VERSION",
    "ApplyResult",
    "ApplyStatus",
    "FileStateEntry",
    "ManagedBlock",
    "ManagedFile",
    "ManagedFileConflict",
    "ManagedFileError",
    "ManagedFileState",
    "ManagedJsonKeys",
    "MergeMode",
    "apply_managed_file",
    "diagnostic_code_skills",
    "diff_managed_file",
    "iter_skills",
    "load_agents_source",
    "load_state",
    "pack_files",
    "read_pack_text",
    "skill_diagnostic_codes",
]
