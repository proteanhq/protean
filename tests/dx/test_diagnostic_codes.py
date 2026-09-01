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


def test_block_list_skips_a_blank_line(tmp_path, monkeypatch):
    # A blank line inside a block sequence is skipped, not a terminator: the item
    # after the gap is still part of the same list (this is what YAML does). The
    # deeper second item pins the branch — if the blank-line skip were dropped,
    # the scan would break on the gap and never reach CROSS_AGGREGATE_REFERENCE.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "\n"
        "    - CROSS_AGGREGATE_REFERENCE\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "CROSS_AGGREGATE_REFERENCE",
    ]


def test_block_list_stops_at_a_sibling_mapping_key(tmp_path, monkeypatch):
    # A sibling mapping key at the key's own indentation ends the sequence and is
    # not swept in, even without a blank line between them.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "  category: x\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


def test_block_list_reads_items_at_the_key_indentation(tmp_path, monkeypatch):
    # A block sequence whose items sit at the key's own indentation is valid YAML
    # and the seed does not use it. The items must still be read, not dropped.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "  - AGGREGATE_NO_INVARIANTS\n"
        "  - CROSS_AGGREGATE_REFERENCE\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "CROSS_AGGREGATE_REFERENCE",
    ]


def test_block_list_reads_tab_indented_items(tmp_path, monkeypatch):
    # Tab-indented items under a space-indented key: measured by visual width, a
    # tab is deeper than two spaces, so the items are read rather than dropped as
    # shallower than the key.
    _write_skill(
        tmp_path,
        "demo",
        "---\nmetadata:\n  diagnostic_codes:\n\t- AGGREGATE_NO_INVARIANTS\n---\n",
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


def test_block_list_stops_at_an_item_shallower_than_the_key(tmp_path, monkeypatch):
    # The first item sets the sequence indentation, but only if it is at least as
    # deep as the diagnostic_codes key. An item indented less than the key is not
    # that key's sequence, so nothing is collected.
    _write_skill(
        tmp_path,
        "demo",
        "---\nmetadata:\n  diagnostic_codes:\n - AGGREGATE_NO_INVARIANTS\n---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == []


# --- Contract enforcement: codes live under metadata, in a closed block ------


def test_diagnostic_codes_outside_metadata_are_not_read(tmp_path, monkeypatch):
    # The contract is metadata.diagnostic_codes. A top-level diagnostic_codes key
    # with no metadata block is not the contract and must be ignored, so a
    # misplaced declaration reads as "teaches nothing" rather than silently
    # working off-contract.
    _write_skill(
        tmp_path,
        "demo",
        "---\ndiagnostic_codes:\n  - AGGREGATE_NO_INVARIANTS\n---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == []


def test_metadata_block_ends_at_the_next_top_level_key(tmp_path, monkeypatch):
    # The metadata block is the run of lines indented under the key, and it ends
    # at the next top-level key. A diagnostic_codes key nested under a *later*
    # top-level key is outside metadata and is not read.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  category: orientation\n"
        "name: demo\n"
        "extra:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == []


def test_unterminated_frontmatter_is_not_read(tmp_path, monkeypatch):
    # An opening fence with no closing fence is malformed. The body is not treated
    # as frontmatter, so a diagnostic_codes key in it declares nothing.
    _write_skill(
        tmp_path,
        "demo",
        "---\nmetadata:\n  diagnostic_codes:\n    - AGGREGATE_NO_INVARIANTS\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == []


def test_inline_list_strips_a_trailing_comment(tmp_path, monkeypatch):
    # A YAML end-of-line comment after an inline list is not part of the value.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes: [AGGREGATE_NO_INVARIANTS]  # the invariants nudge\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


def test_block_item_strips_a_comment_and_quotes(tmp_path, monkeypatch):
    # A block item carrying a trailing comment or wrapped in quotes yields the
    # bare code, not the decorated string.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS  # the invariants nudge\n"
        '    - "CROSS_AGGREGATE_REFERENCE"\n'
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "CROSS_AGGREGATE_REFERENCE",
    ]


def test_duplicate_codes_are_de_duplicated(tmp_path, monkeypatch):
    # A skill that declares the same code twice teaches it once; the wire list
    # must not carry a duplicate.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


def test_reverse_index_de_duplicates_skill_names(monkeypatch):
    # Two skills, one of them named twice by iter_skills (a defensive case): the
    # reverse index lists each teaching skill once.
    monkeypatch.setattr(pack, "iter_skills", lambda: ["alpha", "alpha"])
    monkeypatch.setattr(
        pack, "skill_diagnostic_codes", lambda name: ["AGGREGATE_NO_INVARIANTS"]
    )

    assert pack.diagnostic_code_skills() == {"AGGREGATE_NO_INVARIANTS": ["alpha"]}


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
