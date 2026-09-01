"""The DX-pack diagnostic-code contract and its read path.

A skill declares the diagnostic codes it teaches under
``metadata.diagnostic_codes`` in its ``SKILL.md`` frontmatter; the framework
reads them back through :mod:`protean.dx.pack`. These tests hold both directions
of the catalog honest — every declared code is a real
:class:`~protean.ir.diagnostics.DiagnosticCode`, and every skill named in the
reverse index exists — and cover the frontmatter parser, its pack-absent
tolerance, and the ``teaching_skills`` key :func:`build_diagnostic` attaches.
"""

from __future__ import annotations

import pytest

from protean.dx import pack
from protean.ir.diagnostics import DiagnosticCode, build_diagnostic

# These read package data and build diagnostics directly; they never touch a
# Domain, so skip the autouse test_domain fixture and its initialization cost.
pytestmark = pytest.mark.no_test_domain


@pytest.fixture(autouse=True)
def _clear_reverse_index_cache():
    # The reverse index is cached. Clear it around every test so a monkeypatched
    # fake pack never leaks into another test (or out of this file), and the
    # real-pack tests never read a fake index a prior test cached. A test may
    # replace diagnostic_code_skills outright (to make the lookup raise), so
    # clear only when the real cached function is in place.
    def _clear():
        clear = getattr(pack.diagnostic_code_skills, "cache_clear", None)
        if clear is not None:
            clear()

    _clear()
    yield
    _clear()


def _write_skill(root, name: str, body: str) -> None:
    skill_dir = root / pack.SKILLS_DIR / name
    skill_dir.mkdir(parents=True)
    (skill_dir / pack.SKILL_FILE).write_text(body, encoding="utf-8")


# --- Bidirectional catalog over the real, shipped pack ----------------------


def test_every_declared_code_is_a_real_diagnostic_code():
    valid = {code.value for code in DiagnosticCode}
    declared = {
        code
        for skill in pack.iter_skills()
        for code in pack.skill_diagnostic_codes(skill)
    }

    # Vacuous-pass guard: a run where no skill declares a code fails here rather
    # than passing the emptiness checks below silently.
    assert declared, "no DX-pack skill declares any diagnostic code"
    unknown = declared - valid
    assert not unknown, (
        f"DX-pack skills declare codes absent from DiagnosticCode: {sorted(unknown)}"
    )


def test_every_skill_in_the_reverse_index_exists():
    skills = set(pack.iter_skills())
    named = {name for names in pack.diagnostic_code_skills().values() for name in names}

    assert named, "the reverse index names no skills"
    dangling = named - skills
    assert not dangling, (
        f"the reverse index names skills not in the pack: {sorted(dangling)}"
    )


def test_reverse_index_maps_the_seed_code_to_the_seed_skill():
    assert pack.diagnostic_code_skills()["AGGREGATE_NO_INVARIANTS"] == [
        "protean-overview"
    ]


# --- Surfacing on a built diagnostic ----------------------------------------


def test_build_diagnostic_surfaces_teaching_skills():
    diag = build_diagnostic(
        DiagnosticCode.AGGREGATE_NO_INVARIANTS,
        element="my_app.Order",
        message="Order declares no invariants.",
    )

    assert diag["teaching_skills"] == ["protean-overview"]


def test_build_diagnostic_omits_teaching_skills_when_no_skill_teaches():
    # A real code that no seed skill declares: the key must be absent entirely,
    # mirroring the resolving_operation-absent case.
    taught = set(pack.diagnostic_code_skills())
    untaught = next(code for code in DiagnosticCode if code.value not in taught)

    diag = build_diagnostic(untaught, element="my_app.Thing", message="msg")

    assert "teaching_skills" not in diag


# --- Frontmatter parser (monkeypatched fake pack) ---------------------------


def test_skill_diagnostic_codes_reads_block_list(tmp_path, monkeypatch):
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "name: demo\n"
        "metadata:\n"
        "  category: x\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "    - CROSS_AGGREGATE_REFERENCE\n"
        "---\n\n# Demo\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "CROSS_AGGREGATE_REFERENCE",
    ]


def test_skill_diagnostic_codes_reads_inline_list(tmp_path, monkeypatch):
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes: [AGGREGATE_NO_INVARIANTS, EVENT_WITHOUT_DATA]\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "EVENT_WITHOUT_DATA",
    ]


def test_skill_diagnostic_codes_empty_without_the_key(tmp_path, monkeypatch):
    _write_skill(
        tmp_path,
        "demo",
        "---\nname: demo\nmetadata:\n  category: x\n---\n# body only\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == []


def test_skill_diagnostic_codes_empty_without_frontmatter(tmp_path, monkeypatch):
    _write_skill(tmp_path, "demo", "# A heading, no frontmatter fence at all\n")
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == []


def test_skill_diagnostic_codes_ignores_blank_lines_before_the_fence(
    tmp_path, monkeypatch
):
    # Blank lines before the opening fence are skipped, not treated as "no
    # frontmatter". The fence still opens the block and the key is read.
    _write_skill(
        tmp_path,
        "demo",
        "\n\n---\nmetadata:\n  diagnostic_codes:\n    - AGGREGATE_NO_INVARIANTS\n---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


def test_block_list_stops_at_a_blank_line(tmp_path, monkeypatch):
    # A blank line ends the block list; a later mapping key is not swept in.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "\n"
        "  category: x\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


def test_block_list_stops_at_a_dedented_item(tmp_path, monkeypatch):
    # A list item dedented to the key's own indentation is outside the block and
    # is not swept in: the scan stops at the first item that is not deeper than
    # the diagnostic_codes key.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "  - CROSS_AGGREGATE_REFERENCE\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


def test_reverse_index_inverts_and_sorts_skill_names(tmp_path, monkeypatch):
    # Two skills, created out of alphabetical order, both teaching CODE_X: the
    # reverse index inverts the map and sorts each skill list deterministically.
    _write_skill(
        tmp_path,
        "beta",
        "---\nmetadata:\n  diagnostic_codes:\n    - CODE_X\n---\n",
    )
    _write_skill(
        tmp_path,
        "alpha",
        "---\nmetadata:\n  diagnostic_codes:\n    - CODE_X\n    - CODE_Y\n---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.diagnostic_code_skills() == {
        "CODE_X": ["alpha", "beta"],
        "CODE_Y": ["alpha"],
    }


def test_reverse_index_skips_a_skill_that_fails_to_read(monkeypatch):
    # iter_skills names a skill whose SKILL.md cannot be read: the reverse index
    # skips it and keeps the skills that read cleanly, rather than failing whole.
    monkeypatch.setattr(pack, "iter_skills", lambda: ["good", "bad"])

    def _read(name):
        if name == "bad":
            raise OSError("unreadable skill manifest")
        return ["AGGREGATE_NO_INVARIANTS"]

    monkeypatch.setattr(pack, "skill_diagnostic_codes", _read)

    assert pack.diagnostic_code_skills() == {"AGGREGATE_NO_INVARIANTS": ["good"]}


# --- Pack-absent tolerance --------------------------------------------------


def test_reverse_index_tolerates_pack_absent(monkeypatch):
    def _stripped():
        raise FileNotFoundError("pack data stripped from the install")

    monkeypatch.setattr(pack, "pack_files", _stripped)

    assert pack.diagnostic_code_skills() == {}


def test_build_diagnostic_tolerates_pack_absent(monkeypatch):
    def _stripped():
        raise FileNotFoundError("pack data stripped from the install")

    monkeypatch.setattr(pack, "pack_files", _stripped)

    diag = build_diagnostic(
        DiagnosticCode.AGGREGATE_NO_INVARIANTS,
        element="my_app.Order",
        message="Order declares no invariants.",
    )

    assert "teaching_skills" not in diag


def test_build_diagnostic_tolerates_a_reverse_index_that_raises(monkeypatch):
    # The reverse-index lookup itself blowing up (not just a stripped pack) is
    # swallowed by build_diagnostic: the key is omitted, the diagnostic stands.
    def _boom():
        raise RuntimeError("reverse index build failed")

    monkeypatch.setattr(pack, "diagnostic_code_skills", _boom)

    diag = build_diagnostic(
        DiagnosticCode.AGGREGATE_NO_INVARIANTS,
        element="my_app.Order",
        message="Order declares no invariants.",
    )

    assert "teaching_skills" not in diag
