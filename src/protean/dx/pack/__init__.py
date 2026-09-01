"""The versioned developer-experience pack, shipped as package data.

The pack is the canonical, version-coupled body of agent-facing knowledge that
travels inside the ``protean`` wheel: an AGENTS.md source and the teaching
skills. It lives in the same distribution as the framework, so an agent always
reads guidance that matches the installed code.

Read the pack at runtime through ``importlib.resources`` so it keeps working
when ``protean`` is installed zipped. The accessor mirrors the shape of
:mod:`protean.ir`: module-level constants plus ``load_*`` helpers. The pack's
data files (``AGENTS.md``, ``skills/``) sit beside this module and are reached
through :func:`pack_files`.
"""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable

import protean

__all__ = [
    "AGENTS_SOURCE",
    "PACK_VERSION",
    "SKILLS_DIR",
    "SKILL_FILE",
    "iter_skills",
    "load_agents_source",
    "pack_files",
    "read_pack_text",
]

# The pack ships inside the wheel, so its version is the framework version. A
# consumer stamps this to tell which framework version's guidance the pack
# carries. ``protean.__version__`` is the framework's single version source,
# moved mechanically by bump-my-version, so the stamp stays in step with the
# content it labels.
PACK_VERSION = protean.__version__

# Well-known names within the pack: the AGENTS.md source and the skills
# directory sit at the pack root; each skill directory holds a SKILL.md.
AGENTS_SOURCE = "AGENTS.md"
SKILLS_DIR = "skills"
SKILL_FILE = "SKILL.md"


def pack_files() -> Traversable:
    """Return the pack root as an ``importlib.resources`` traversable."""
    return resources.files(__name__)


def read_pack_text(*parts: str) -> str:
    """Read a text resource from the pack, addressed by its path parts.

    Each part is a single path segment. A segment that is empty, ``.`` or
    ``..``, or that contains a path separator is rejected, so a caller cannot
    read outside the pack on a filesystem install.
    """
    resource = pack_files()
    for part in parts:
        if not part or part in (".", "..") or "/" in part or "\\" in part:
            raise ValueError(f"invalid pack path segment: {part!r}")
        resource = resource / part
    return resource.read_text(encoding="utf-8")


def load_agents_source() -> str:
    """Return the packaged AGENTS.md source text."""
    return read_pack_text(AGENTS_SOURCE)


def iter_skills() -> list[str]:
    """Return the names of the skills bundled in the pack, sorted.

    A skill is a directory under ``skills/`` that holds a ``SKILL.md``. Any
    other entry (a stray file, or a directory without a manifest) is ignored.
    """
    skills_root = pack_files() / SKILLS_DIR
    return sorted(
        child.name
        for child in skills_root.iterdir()
        if child.is_dir() and (child / SKILL_FILE).is_file()
    )
