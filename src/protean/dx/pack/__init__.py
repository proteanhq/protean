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
# The scanner honours the parts of YAML that a real author reasonably relies on:
# the ``metadata`` nesting the contract promises, tab or space indentation,
# same-indent or deeper block sequences, comment lines and end-of-line
# comments, and quoted scalars. It is deliberately narrow, not a general YAML
# reader.
_FRONTMATTER_FENCE = "---"
_METADATA_KEY = "metadata"
_DIAGNOSTIC_CODES_KEY = "diagnostic_codes"
_BLOCK_ITEM = re.compile(r"^\s*-\s*(.+?)\s*$")


def _indent(line: str) -> int:
    """Return the line's visual indentation width, with tabs expanded.

    A tab and a run of spaces can produce the same visual indent, so measure the
    expanded width rather than the raw character count. Otherwise a tab-indented
    item under a space-indented key looks shallower than it is and is dropped.
    """
    leading = line[: len(line) - len(line.lstrip())]
    return len(leading.expandtabs())


def _skippable(line: str) -> bool:
    """Return whether YAML ignores this line wherever it appears in a block.

    A blank line and a comment-only line carry no structure, so neither one ends
    a mapping block or a block sequence.
    """
    stripped = line.strip()
    return stripped == "" or stripped.startswith("#")


def _strip_comment(value: str) -> str:
    """Drop a YAML end-of-line ``#`` comment (one preceded by whitespace)."""
    for index in range(1, len(value)):
        if value[index] == "#" and value[index - 1] in " \t":
            return value[:index].rstrip()
    return value


def _clean_scalar(value: str) -> str:
    """Trim one scalar: drop a trailing comment and matching surrounding quotes."""
    value = _strip_comment(value.strip()).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value


def _dedup(items: list[str]) -> list[str]:
    """Drop duplicate items, keeping first-seen order."""
    return list(dict.fromkeys(items))


def _frontmatter_lines(text: str) -> list[str]:
    """Return the lines inside a SKILL.md's leading ``---``-fenced block.

    A skill with no frontmatter (no opening fence on its first non-empty line)
    yields no lines. An opening fence with no closing fence is malformed and also
    yields no lines, so an unterminated block is not read as frontmatter. The
    closing fence and everything after it is dropped.
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
            return body
        body.append(line)
    return []


def _split_inline_list(value: str) -> list[str]:
    """Split an inline ``[A, B]`` list into its cleaned, non-empty items."""
    value = _strip_comment(value.strip()).strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items = [_clean_scalar(item) for item in value.split(",")]
    return [item for item in items if item]


def _metadata_block(lines: list[str]) -> list[str] | None:
    """Return the lines inside the top-level ``metadata:`` mapping, or ``None``.

    ``metadata`` must be a top-level frontmatter key (indent 0) with no inline
    value; the block is the run of following lines indented under it, ending at
    the next top-level key. Blank and comment-only lines carry no structure, so
    an unindented one does not end the block. Returns ``None`` when no such key
    exists, so a skill with no ``metadata`` block declares nothing and a stray
    ``diagnostic_codes`` outside ``metadata`` is not read.
    """
    start = None
    for index, line in enumerate(lines):
        if _skippable(line) or _indent(line) != 0:
            continue
        head, sep, rest = line.strip().partition(":")
        if sep and head == _METADATA_KEY and rest.strip() == "":
            start = index
            break
    if start is None:
        return None
    block: list[str] = []
    for line in lines[start + 1 :]:
        if not _skippable(line) and _indent(line) == 0:
            break
        block.append(line)
    return block


def _collect_block_list(lines: list[str], key_indent: int) -> list[str]:
    """Collect a YAML block sequence's items following its ``key:`` line.

    Items are ``- VALUE`` lines that share one indentation: the first item sets
    it, and it must be at least the key's indentation (a shallower item belongs
    to a parent). Blank and comment-only lines within the sequence are skipped.
    The sequence ends at the first line that is not one of those and not an item
    at that indentation: a sibling mapping key, a dedent, or a re-indented item.
    """
    codes: list[str] = []
    seq_indent: int | None = None
    for line in lines:
        if _skippable(line):
            continue
        match = _BLOCK_ITEM.match(line)
        if match is None:
            break
        indent = _indent(line)
        if seq_indent is None:
            if indent < key_indent:
                break
            seq_indent = indent
        elif indent != seq_indent:
            break
        codes.append(_clean_scalar(match.group(1)))
    return codes


def _parse_diagnostic_codes(lines: list[str]) -> list[str]:
    """Read ``metadata.diagnostic_codes`` from frontmatter ``lines``.

    The key must sit inside the top-level ``metadata`` mapping, as the contract
    promises. Reads both the block-list form (``- CODE`` on its own indented
    line) and the inline form (``[CODE, CODE]``) after the key, and de-duplicates
    the result. Returns ``[]`` when there is no ``metadata`` block or no
    ``diagnostic_codes`` key, so a skill that teaches no coded rule declares
    nothing.
    """
    block = _metadata_block(lines)
    if block is None:
        return []
    for index, line in enumerate(block):
        head, sep, rest = line.strip().partition(":")
        if not sep or head != _DIAGNOSTIC_CODES_KEY:
            continue
        inline = rest.strip()
        if inline:
            return _dedup(_split_inline_list(inline))
        return _dedup(_collect_block_list(block[index + 1 :], _indent(line)))
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

    Built by reading every skill's declared codes and inverting the map, with
    each code's skill list sorted and de-duplicated. The result is cached; call
    ``diagnostic_code_skills.cache_clear()`` after pointing the accessor at a
    different pack (tests do this). Degrades rather than raises when the pack is
    incomplete: a failure listing the skills yields an empty index, and a failure
    reading one skill skips that skill and keeps the rest. So a caller in core IR
    keeps working when the pack is stripped from the wheel.
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
    return {code: sorted(set(names)) for code, names in index.items()}
