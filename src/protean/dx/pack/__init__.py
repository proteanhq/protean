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

import re
from functools import lru_cache
from importlib import resources
from importlib.resources.abc import Traversable

import protean

__all__ = [
    "AGENTS_SOURCE",
    "PACK_VERSION",
    "SKILLS_DIR",
    "SKILL_FILE",
    "diagnostic_code_skills",
    "iter_skills",
    "load_agents_source",
    "pack_files",
    "read_pack_text",
    "skill_diagnostic_codes",
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


# A skill declares the diagnostic codes it teaches under
# ``metadata.diagnostic_codes`` in the leading ``---``-fenced frontmatter of its
# SKILL.md. The pack format is under the framework's control, so a small
# line-scanner reads that one key without a YAML dependency (the repo has none).
_FRONTMATTER_FENCE = "---"
_DIAGNOSTIC_CODES_KEY = "diagnostic_codes"
_BLOCK_ITEM = re.compile(r"^\s*-\s*(.+?)\s*$")


def _frontmatter_lines(text: str) -> list[str]:
    """Return the lines inside a SKILL.md's leading ``---``-fenced block.

    A skill with no frontmatter (no opening fence on its first non-empty line)
    yields no lines. The closing fence and everything after it is dropped.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "":
            continue
        if line.strip() == _FRONTMATTER_FENCE:
            start = index
        break
    if start is None:
        return []
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() == _FRONTMATTER_FENCE:
            break
        body.append(line)
    return body


def _split_inline_list(value: str) -> list[str]:
    """Split an inline ``[A, B]`` list into its trimmed, non-empty items."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_diagnostic_codes(lines: list[str]) -> list[str]:
    """Read the ``diagnostic_codes`` value from frontmatter ``lines``.

    Reads both the block-list form (``- CODE`` on its own indented line) and the
    inline form (``[CODE, CODE]``) after the key. Returns ``[]`` when the key is
    absent, so a skill that teaches no coded rule declares nothing.
    """
    for index, line in enumerate(lines):
        head, sep, rest = line.strip().partition(":")
        if not sep or head != _DIAGNOSTIC_CODES_KEY:
            continue
        inline = rest.strip()
        if inline:
            return _split_inline_list(inline)
        key_indent = len(line) - len(line.lstrip())
        codes: list[str] = []
        for follow in lines[index + 1 :]:
            if follow.strip() == "":
                break
            follow_indent = len(follow) - len(follow.lstrip())
            match = _BLOCK_ITEM.match(follow)
            if match is None or follow_indent <= key_indent:
                break
            codes.append(match.group(1).strip())
        return codes
    return []


def skill_diagnostic_codes(name: str) -> list[str]:
    """Return the diagnostic codes the named skill declares it teaches.

    A skill points at the codes (the source of truth is
    :class:`~protean.ir.diagnostics.DiagnosticCode`) under
    ``metadata.diagnostic_codes`` in its ``SKILL.md`` frontmatter, so there is
    no framework-owned map to drift. A skill with no frontmatter, no
    ``metadata`` block, or no ``diagnostic_codes`` key declares nothing and
    returns ``[]``.
    """
    text = read_pack_text(SKILLS_DIR, name, SKILL_FILE)
    return _parse_diagnostic_codes(_frontmatter_lines(text))


@lru_cache(maxsize=1)
def diagnostic_code_skills() -> dict[str, list[str]]:
    """Return the reverse index: each diagnostic code to the sorted skills that
    teach it.

    Built by reading every skill's declared codes and inverting the map. The
    result is cached; call ``diagnostic_code_skills.cache_clear()`` after
    pointing the accessor at a different pack (tests do this). Tolerates a
    pack-absent install: any read failure yields an empty index, so a caller in
    core IR keeps working when the pack is stripped from the wheel.
    """
    index: dict[str, list[str]] = {}
    try:
        skills = iter_skills()
    except Exception:
        return {}
    for skill in skills:
        try:
            codes = skill_diagnostic_codes(skill)
        except Exception:
            continue
        for code in codes:
            index.setdefault(code, []).append(skill)
    return {code: sorted(names) for code, names in index.items()}
