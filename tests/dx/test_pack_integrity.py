"""Guard the internal references inside the DX pack.

``test_examples.py`` proves every ``assets/*.py`` builds a real domain.
``test_pack.py`` proves the skill, references, and rules layers survive a
re-sync. Neither one checks that a skill's own links point at files that exist.
This guard closes that gap: it walks the pack and fails on a dangling internal
reference, an asset or reference page no skill links, or a skill whose recipe
does not link the shared verify step.

The scanner is a plain function over a pack root, so the negative tests can point
it at a small fake pack built under ``tmp_path`` and prove each failure names the
offending skill and token. The positive test points it at the shipped pack and
requires a clean report.

What the scanner recognizes as an internal reference is deliberately narrow, so a
templated token in a code fence (``<aggregate>.py``) or a bare filename in prose
(``order_placed.py``) does not read as a broken link. A token counts only when it
is a markdown link target or an inline-code span that, resolved against the file
it sits in, lands on one of: a bundled skill's ``SKILL.md``, a ``.py`` file under
some ``assets/`` directory, a ``.md`` file under some ``references/`` directory,
or a top-level ``rules/*.md`` file. A ``#anchor`` suffix is stripped first, and
tokens inside fenced code blocks are skipped.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from protean import dx

# These tests read package data; they never touch a Domain, so skip the autouse
# test_domain fixture and its initialization cost.
pytestmark = pytest.mark.no_test_domain

# Well-known pack names. The shared verify reference sits at the pack root under
# references/, so a skill reaches it with ../../references/verify-with-check.md.
SKILLS_DIR = "skills"
SKILL_FILE = "SKILL.md"
REFERENCES_DIR = "references"
ASSETS_DIR = "assets"
RULES_DIR = "rules"
VERIFY_REFERENCE = "verify-with-check.md"
HARDENING_BAR = "hardening-bar.md"
# The pack-relative target the shared verify link must resolve to.
VERIFY_TARGET = f"{REFERENCES_DIR}/{VERIFY_REFERENCE}"

PACK_ROOT = Path(str(dx.pack_files()))

# The scanner walks the pack tree, so it needs the pack unpacked on disk. The
# accessor does not promise a filesystem root (a zip install would not have one),
# so the positive test skips cleanly in the zip case; CI installs unzipped.
requires_pack_on_disk = pytest.mark.skipif(
    not PACK_ROOT.is_dir(),
    reason="DX pack is not unpacked on disk; the integrity guard walks the pack tree",
)

_LINK = re.compile(r"\]\(([^)]+)\)")
_INLINE_CODE = re.compile(r"`([^`]+)`")
# A token carrying any of these is a template or a glob, not a concrete path.
_TEMPLATE = re.compile(r"[<>*|\s]")
_FENCE_MARKERS = ("```", "~~~")


@dataclass(frozen=True)
class Reference:
    """One recognized internal reference found inside a pack file."""

    skill: str  # the skill whose SKILL.md or references/ page holds the token
    source: str  # the pack-relative file the token was found in
    token: str  # the token exactly as written, before anchor stripping
    target: str  # the pack-relative path the token resolves to (posix)
    kind: str  # "skill" | "asset" | "reference" | "rules"


@dataclass
class PackIntegrityReport:
    """The outcome of walking the pack for reference integrity."""

    skills: list[str]
    references: list[Reference]
    dangling: list[Reference]
    orphans: list[str]
    skills_missing_verify: list[str]

    def dangling_messages(self) -> list[str]:
        return [
            f"{ref.skill}: {ref.source} links {ref.token!r}, which does not "
            f"resolve (target {ref.target})"
            for ref in self.dangling
        ]


def _lines_outside_fences(text: str) -> list[str]:
    """Return the lines of ``text`` that sit outside fenced code blocks.

    A line whose stripped form opens with ``` or ~~~ toggles the fence and is
    itself dropped. An unterminated fence drops the rest of the file, which is
    the safe reading: a token in an unclosed code block still does not count.
    """
    outside: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith(_FENCE_MARKERS):
            in_fence = not in_fence
            continue
        if not in_fence:
            outside.append(line)
    return outside


def _raw_tokens(text: str) -> list[str]:
    """Return every markdown link target and inline-code span outside fences."""
    body = "\n".join(_lines_outside_fences(text))
    tokens: list[str] = [match.group(1).strip() for match in _LINK.finditer(body)]
    tokens += [match.group(1).strip() for match in _INLINE_CODE.finditer(body)]
    return tokens


def _classify(root: Path, skill: str, source: Path, token: str) -> Reference | None:
    """Resolve one token and classify it, or return ``None`` if it is not a
    recognized internal reference.

    The token is resolved against the directory of the file it sits in, so a
    peer skill's reference page (``../peer/references/page.md`` from a SKILL.md)
    lands on that peer, not on the current skill. Anything that resolves outside
    the pack, is a template or glob, is an external URL, or does not land on one
    of the four recognized shapes is left unscanned.
    """
    stripped = token.split("#", 1)[0].strip()
    if not stripped or _TEMPLATE.search(stripped):
        return None
    if stripped.startswith(("http://", "https://", "mailto:", "/")):
        return None
    if not stripped.endswith((".md", ".py")):
        return None

    resolved = (source.parent / stripped).resolve()
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        return None

    parts = rel.parts
    if rel.name == SKILL_FILE:
        kind = "skill"
    elif stripped.endswith(".py") and ASSETS_DIR in parts:
        kind = "asset"
    elif stripped.endswith(".md") and REFERENCES_DIR in parts:
        kind = "reference"
    elif stripped.endswith(".md") and len(parts) == 2 and parts[0] == RULES_DIR:
        kind = "rules"
    else:
        return None

    return Reference(
        skill=skill,
        source=source.relative_to(root).as_posix(),
        token=token,
        target=rel.as_posix(),
        kind=kind,
    )


def _references_in(root: Path, skill: str, source: Path) -> list[Reference]:
    """Return every recognized internal reference in one pack file."""
    text = source.read_text(encoding="utf-8")
    found: list[Reference] = []
    for token in _raw_tokens(text):
        ref = _classify(root, skill, source, token)
        if ref is not None:
            found.append(ref)
    return found


def _skill_sources(skill_dir: Path) -> list[Path]:
    """Return the files scanned for one skill: its SKILL.md and its reference
    pages. Pack-level references and rules are link targets, never sources, so a
    note that mentions a file name in prose cannot itself raise a false dangling
    finding."""
    sources = [skill_dir / SKILL_FILE]
    sources += sorted((skill_dir / REFERENCES_DIR).glob("*.md"))
    return sources


def _reachable_files(root: Path, skill: str, skill_dir: Path) -> set[str]:
    """Return the pack-relative asset and reference files reachable from the
    skill's SKILL.md.

    Reachability is transitive through reference pages: the SKILL.md names files
    directly, and a reference page it reaches can name further files (an asset
    via ``../assets/x.py``, a sibling page via ``./y.md``). Only targets inside
    this skill count; a cross-skill link is a separate concern.
    """
    prefix = f"{SKILLS_DIR}/{skill}/"
    reachable: set[str] = set()
    frontier: list[Path] = [skill_dir / SKILL_FILE]
    scanned: set[str] = set()
    while frontier:
        source = frontier.pop()
        key = source.as_posix()
        if key in scanned:
            continue
        scanned.add(key)
        for ref in _references_in(root, skill, source):
            if ref.kind not in ("asset", "reference"):
                continue
            if not ref.target.startswith(prefix):
                continue
            reachable.add(ref.target)
            target_path = root / ref.target
            if ref.kind == "reference" and target_path.is_file():
                frontier.append(target_path)
    return reachable


def _skill_asset_and_reference_files(root: Path, skill_dir: Path) -> list[str]:
    """Return the pack-relative asset and reference files a skill ships.

    Excludes ``assets/__init__.py`` package markers, which are never linked and
    define no example (the example runner skips them too).
    """
    files: list[str] = [
        path.relative_to(root).as_posix()
        for path in sorted((skill_dir / ASSETS_DIR).glob("*.py"))
        if path.name != "__init__.py"
    ]
    files += [
        path.relative_to(root).as_posix()
        for path in sorted((skill_dir / REFERENCES_DIR).glob("*.md"))
    ]
    return files


def scan_pack(pack_root: Path) -> PackIntegrityReport:
    """Walk the pack and report its reference integrity.

    For every skill it collects the recognized references in the SKILL.md and
    every reference page, flags the ones whose target does not exist, flags any
    asset or reference file unreachable from the SKILL.md, and flags a skill
    whose SKILL.md does not link the shared verify reference.
    """
    root = pack_root.resolve()
    skills_root = root / SKILLS_DIR
    skills = sorted(
        child.name
        for child in skills_root.iterdir()
        if child.is_dir() and (child / SKILL_FILE).is_file()
    )

    references: list[Reference] = []
    dangling: list[Reference] = []
    orphans: list[str] = []
    skills_missing_verify: list[str] = []

    for skill in skills:
        skill_dir = skills_root / skill

        skill_md_targets: set[str] = set()
        for source in _skill_sources(skill_dir):
            for ref in _references_in(root, skill, source):
                references.append(ref)
                if not (root / ref.target).exists():
                    dangling.append(ref)
                if source.name == SKILL_FILE:
                    skill_md_targets.add(ref.target)

        if VERIFY_TARGET not in skill_md_targets:
            skills_missing_verify.append(skill)

        reachable = _reachable_files(root, skill, skill_dir)
        orphans += [
            shipped
            for shipped in _skill_asset_and_reference_files(root, skill_dir)
            if shipped not in reachable
        ]

    return PackIntegrityReport(
        skills=skills,
        references=references,
        dangling=dangling,
        orphans=orphans,
        skills_missing_verify=skills_missing_verify,
    )


# --- The shipped pack: it must pass the guard at HEAD ------------------------


@requires_pack_on_disk
def test_shipped_pack_has_no_dangling_references():
    report = scan_pack(PACK_ROOT)

    assert report.dangling == [], "dangling internal references:\n" + "\n".join(
        report.dangling_messages()
    )


@requires_pack_on_disk
def test_shipped_pack_has_no_orphaned_files():
    report = scan_pack(PACK_ROOT)

    assert report.orphans == [], (
        "asset or reference files no SKILL.md reaches:\n" + "\n".join(report.orphans)
    )


@requires_pack_on_disk
def test_every_shipped_skill_links_the_verify_reference():
    report = scan_pack(PACK_ROOT)

    assert report.skills_missing_verify == [], (
        "skills that do not link the shared verify reference:\n"
        + "\n".join(report.skills_missing_verify)
    )


@requires_pack_on_disk
def test_shipped_pack_scan_is_not_vacuous():
    # A scanner that silently matched nothing would pass every assertion above.
    # Pin the pack it walked to the real corpus: every skill it lists is on disk,
    # it found the full skill set, and it resolved a large body of references. A
    # broken matcher that finds no skills or no tokens trips this floor.
    report = scan_pack(PACK_ROOT)

    on_disk = sorted(
        child.name
        for child in (PACK_ROOT / SKILLS_DIR).iterdir()
        if child.is_dir() and (child / SKILL_FILE).is_file()
    )
    assert report.skills == on_disk
    assert len(report.skills) >= 30
    # Floors sit just under the real corpus (756 references: 129 skill, 407
    # reference, 220 asset). A per-kind floor means a matcher that dropped even
    # one working kind trips this, not just one that finds nothing.
    assert len(report.references) >= 700
    by_kind = Counter(ref.kind for ref in report.references)
    assert by_kind["skill"] >= 100
    assert by_kind["reference"] >= 350
    assert by_kind["asset"] >= 180


# --- The shared references: present, non-empty, reachable from the repo ------


@requires_pack_on_disk
def test_verify_reference_is_present_and_non_empty():
    # Read it through the accessor, the same read path the installed wheel uses.
    text = dx.read_pack_text(REFERENCES_DIR, VERIFY_REFERENCE)

    assert text.strip(), "the shared verify reference is empty"
    assert "check" in text


@requires_pack_on_disk
def test_hardening_bar_note_is_present_and_reachable():
    # The maintainer-facing bar lives in the pack and is linked from AGENTS.md,
    # so it is reachable from the repo.
    text = dx.read_pack_text(REFERENCES_DIR, HARDENING_BAR)
    assert text.strip(), "the hardening-bar note is empty"

    agents = dx.load_agents_source()
    assert f"{REFERENCES_DIR}/{HARDENING_BAR}" in agents, (
        "AGENTS.md does not link the hardening-bar note"
    )


# --- Negative fixtures: each break produces a distinct, named finding --------


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# A recipe tail that links the shared verify reference, so a fixture skill is
# clean on the verify check and only the break under test shows up.
_VERIFY_LINK = f"\n\n## Verify\n\n- [verify](../../{VERIFY_TARGET})\n"


def _make_pack(tmp_path: Path) -> Path:
    """Lay down a minimal pack root with the shared verify reference in place."""
    root = tmp_path / "pack"
    _write(root / REFERENCES_DIR / VERIFY_REFERENCE, "# Verify\n\nRun check.\n")
    return root


def _add_skill(
    root: Path,
    name: str,
    body: str,
    *,
    link_verify: bool = True,
    assets: dict[str, str] | None = None,
    references: dict[str, str] | None = None,
) -> None:
    text = f"---\nname: {name}\n---\n\n# {name}\n\n{body}"
    if link_verify:
        text += _VERIFY_LINK
    _write(root / SKILLS_DIR / name / SKILL_FILE, text)
    for filename, content in (assets or {}).items():
        _write(root / SKILLS_DIR / name / ASSETS_DIR / filename, content)
    for filename, content in (references or {}).items():
        _write(root / SKILLS_DIR / name / REFERENCES_DIR / filename, content)


def test_clean_fixture_passes(tmp_path):
    root = _make_pack(tmp_path)
    _add_skill(
        root,
        "alpha",
        "See [page](references/page.md) and [example](assets/example.py).",
        assets={"example.py": "x = 1\n"},
        references={"page.md": "A page.\n"},
    )

    report = scan_pack(root)

    assert report.dangling == []
    assert report.orphans == []
    assert report.skills_missing_verify == []


def test_dangling_cross_link_is_named(tmp_path):
    root = _make_pack(tmp_path)
    _add_skill(root, "alpha", "See [gone](../nonexistent/SKILL.md).")

    report = scan_pack(root)

    assert len(report.dangling) == 1
    finding = report.dangling[0]
    assert finding.skill == "alpha"
    assert finding.token == "../nonexistent/SKILL.md"
    messages = "\n".join(report.dangling_messages())
    assert "alpha" in messages and "../nonexistent/SKILL.md" in messages


def test_missing_referenced_file_is_named(tmp_path):
    root = _make_pack(tmp_path)
    _add_skill(root, "alpha", "See [missing](references/missing.md).")

    report = scan_pack(root)

    assert len(report.dangling) == 1
    finding = report.dangling[0]
    assert finding.skill == "alpha"
    assert finding.token == "references/missing.md"


def test_orphaned_asset_is_named(tmp_path):
    root = _make_pack(tmp_path)
    # SKILL.md links nothing, so the shipped asset is unreachable.
    _add_skill(root, "alpha", "No links here.", assets={"orphan.py": "x = 1\n"})

    report = scan_pack(root)

    assert report.dangling == []
    assert report.orphans == [f"{SKILLS_DIR}/alpha/{ASSETS_DIR}/orphan.py"]


def test_skill_missing_verify_link_is_named(tmp_path):
    root = _make_pack(tmp_path)
    _add_skill(root, "alpha", "A recipe with no verify link.", link_verify=False)

    report = scan_pack(root)

    assert report.dangling == []
    assert report.skills_missing_verify == ["alpha"]


def test_peer_skill_reference_link_resolves(tmp_path):
    # The risk the grammar guards against: a link to a peer skill's reference page
    # must resolve against that peer, not be mis-resolved against the current
    # skill and flagged as dangling.
    root = _make_pack(tmp_path)
    _add_skill(
        root,
        "beta",
        "Beta body.",
        references={"guide.md": "Beta guide.\n"},
    )
    _add_skill(root, "alpha", "See [beta guide](../beta/references/guide.md).")

    report = scan_pack(root)

    assert report.dangling == []


def test_reachable_through_reference_page_is_not_orphaned(tmp_path):
    # An asset the SKILL.md never names directly is still reachable when a
    # reference page the SKILL.md links names it (via ../assets/x.py).
    root = _make_pack(tmp_path)
    _add_skill(
        root,
        "alpha",
        "See the [guide](references/guide.md).",
        assets={"deep.py": "x = 1\n"},
        references={"guide.md": "Runnable: [example](../assets/deep.py).\n"},
    )

    report = scan_pack(root)

    assert report.orphans == []


def test_anchor_suffix_is_stripped_before_resolving(tmp_path):
    # The SKILL.md reaches page.md only through an anchored link. The strip must
    # turn references/page.md#a-heading into references/page.md so it resolves
    # and reaches the shipped page. Without the strip the token keeps its
    # #a-heading tail, fails the .md/.py suffix filter, is dropped, and page.md
    # surfaces as an orphan the SKILL.md never reached.
    root = _make_pack(tmp_path)
    _add_skill(
        root,
        "alpha",
        "See [section](references/page.md#a-heading).",
        references={"page.md": "A page.\n"},
    )

    report = scan_pack(root)

    assert report.dangling == []
    assert report.orphans == []
    resolved = [ref.target for ref in report.references]
    assert f"{SKILLS_DIR}/alpha/{REFERENCES_DIR}/page.md" in resolved


def test_token_only_inside_a_fence_does_not_count(tmp_path):
    # A file mentioned only inside a code fence is not a reference, so the asset
    # it names reads as unlinked and the fence-only mention cannot rescue it.
    root = _make_pack(tmp_path)
    body = "Here is code:\n\n```python\n# see assets/fenced.py\n```\n"
    _add_skill(root, "alpha", body, assets={"fenced.py": "x = 1\n"})

    report = scan_pack(root)

    assert report.orphans == [f"{SKILLS_DIR}/alpha/{ASSETS_DIR}/fenced.py"]


def test_bare_filename_in_prose_is_not_a_reference(tmp_path):
    # A bare filename with no assets/ or references/ prefix (a templated example
    # name in prose) is not a recognized reference, so it raises no dangling
    # finding even though no such file exists.
    root = _make_pack(tmp_path)
    _add_skill(root, "alpha", "Name the file `order_placed.py` in your aggregate.")

    report = scan_pack(root)

    assert report.dangling == []


def test_rules_link_resolves(tmp_path):
    # A top-level rules/*.md target is a recognized reference. A SKILL.md link
    # that resolves to one is clean and shows up under references as kind "rules".
    root = _make_pack(tmp_path)
    _write(root / RULES_DIR / "naming.md", "Naming rule.\n")
    _add_skill(root, "alpha", "Follow [naming](../../rules/naming.md).")

    report = scan_pack(root)

    assert report.dangling == []
    resolved = [(ref.kind, ref.target) for ref in report.references]
    assert ("rules", f"{RULES_DIR}/naming.md") in resolved


def test_dangling_rules_link_is_named(tmp_path):
    # A link to a missing top-level rules/*.md is a dangling reference, named as
    # kind "rules" so the finding points at the right layer.
    root = _make_pack(tmp_path)
    _add_skill(root, "alpha", "Follow [gone](../../rules/missing.md).")

    report = scan_pack(root)

    assert len(report.dangling) == 1
    finding = report.dangling[0]
    assert finding.skill == "alpha"
    assert finding.kind == "rules"
    assert finding.token == "../../rules/missing.md"
