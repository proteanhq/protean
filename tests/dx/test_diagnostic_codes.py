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
from protean.ir.diagnostics import REGISTRY, DiagnosticCode, build_diagnostic

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


# --- Coverage guard: every coverable lint code has a teaching skill --------

# Lint codes no skill teaches today, with the reason it is excluded rather than
# required to gain one. #1558's Decisions block permits this explicitly: "If a
# specific lint code should not require a skill, it is named on the same
# exclusion list." A code that gains a skill must come off this list, and the
# partition test below catches a code that is neither taught nor excluded.
_UNCOVERED_LINT_CODES = {
    # A deprecation notice's fix is specific to the API being deprecated, not a
    # reusable modeling convention a skill teaches.
    "DEPRECATED_CONFIG": "deprecation notice; fix is API-specific",
    "DEPRECATED_ELEMENT": "deprecation notice; fix is API-specific",
    "DEPRECATED_EMAIL": "deprecation notice; fix is API-specific",
    "DEPRECATED_FIELD": "deprecation notice; fix is API-specific",
    "DEPRECATED_IMPORT": "deprecation notice; fix is API-specific",
    "DEPRECATED_OPTION": "deprecation notice; fix is API-specific",
    # No teaching skill exists in the pack for these conventions yet.
    "ADAPTER_CALL_IN_DOMAIN": "no teaching skill in the pack yet",
    "INFRA_IMPORT_IN_DOMAIN": "no teaching skill in the pack yet",
    "LOW_POOL_SIZE": "no teaching skill in the pack yet",
    "PUBLISHED_NO_EXTERNAL_BROKER": "no teaching skill in the pack yet",
}


def _lint_codes() -> set[str]:
    return {code.value for code in DiagnosticCode if REGISTRY[code].kind == "lint"}


def _coverable_codes() -> set[str]:
    """Lint codes a skill is required to teach: every lint code minus the
    documented exclusion list."""
    return _lint_codes() - set(_UNCOVERED_LINT_CODES)


class TestDiagnosticCodeCoverageGuard:
    def test_exclusion_list_codes_are_really_lint(self):
        # A typo-guard: an exclusion-list entry that is not actually a lint code
        # (say, a `raise` code mistyped) would hide the real gap it claims to
        # explain, rather than excusing it.
        not_lint = {
            code
            for code in _UNCOVERED_LINT_CODES
            if REGISTRY[DiagnosticCode[code]].kind != "lint"
        }
        assert not not_lint, (
            f"exclusion-list entries are not kind='lint' codes: {sorted(not_lint)}"
        )

    def test_coverable_and_excluded_partition_the_whole_catalog(self):
        # Every DiagnosticCode is either coverable (a lint code a skill must
        # teach) or excluded (a raise/staleness code, or a documented
        # exclusion). A new code lands in neither set and reds here, forcing
        # the choice the guard exists to force.
        all_codes = {code.value for code in DiagnosticCode}
        non_lint_codes = all_codes - _lint_codes()
        excluded = non_lint_codes | set(_UNCOVERED_LINT_CODES)
        coverable = _coverable_codes()

        assert coverable.isdisjoint(excluded), (
            f"a code is both coverable and excluded: {sorted(coverable & excluded)}"
        )
        assert coverable | excluded == all_codes, (
            "coverable and excluded codes do not cover the whole catalog; "
            f"missing: {sorted(all_codes - (coverable | excluded))}"
        )

    def test_every_coverable_code_has_a_teaching_skill(self):
        coverable = _coverable_codes()
        # Vacuous-pass guard: an empty coverable set would make the check below
        # pass with nothing actually asserted.
        assert coverable, "no coverable lint codes found"

        taught = set(pack.diagnostic_code_skills())
        untaught = coverable - taught

        assert not untaught, (
            "these lint codes are neither taught by a DX-pack skill nor on the "
            f"documented exclusion list: {sorted(untaught)}. Add a teaching "
            "skill declaration, or add the code to _UNCOVERED_LINT_CODES with "
            "a reason."
        )


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


# The workflow/refactor/analysis family (#1554). The six skills that teach a
# coded fix pin to their exact declared codes; the eight that teach none pin to
# an empty list. Scoped to this family's own skills so the building-block and
# event/CQRS passes can add their declarations without colliding here.
_FAMILY_CODE_TEACHING_SKILLS = {
    "add-field": ["UNBOUNDED_INDEXED_STRING", "UNINDEXED_FILTER_PATH"],
    "add-validation": ["AGGREGATE_NO_INVARIANTS", "VALUE_OBJECT_INVARIANT_FAILED"],
    "add-read-model": ["PROJECTION_WITHOUT_PROJECTOR", "UNSOURCED_PROJECTION_FIELD"],
    "add-saga-flow": ["PROCESS_MANAGER_UNCLOSED"],
    "refactor-extract-value-object": ["VALUE_OBJECT_MUTABLE_FIELD"],
    "refactor-introduce-events": ["EVENT_WITHOUT_DATA", "UNRAISED_EVENT"],
    "refactor-move-logic-to-aggregate": ["AGGREGATE_NO_INVARIANTS"],
    "split-aggregate": ["AGGREGATE_TOO_LARGE", "CROSS_AGGREGATE_REFERENCE"],
}

_FAMILY_NO_CODE_SKILLS = [
    "add-command",
    "add-event",
    "add-use-case",
    "add-domain-service-flow",
    "add-subscriber-flow",
    "coverage-analysis",
    "generate-test-scaffold",
    "audit-domain",
]


@pytest.mark.parametrize(
    ("skill", "expected"), sorted(_FAMILY_CODE_TEACHING_SKILLS.items())
)
def test_family_skill_declares_its_exact_codes(skill, expected):
    # Pin each code-teaching skill in this family to the exact list it declares,
    # so dropping or mistyping a code in its frontmatter reds here rather than
    # slipping through the "is a real DiagnosticCode" check above.
    assert pack.skill_diagnostic_codes(skill) == expected


@pytest.mark.parametrize("skill", _FAMILY_NO_CODE_SKILLS)
def test_family_skill_that_teaches_no_code_declares_none(skill):
    # The workflow and analysis skills that compose element skills without
    # teaching a coded convention declare no diagnostic codes. Pin the negative
    # direction so a stray declaration on one of them is caught.
    assert pack.skill_diagnostic_codes(skill) == []


@pytest.mark.parametrize(
    ("skill", "expected"), sorted(_FAMILY_CODE_TEACHING_SKILLS.items())
)
def test_family_skill_names_every_code_it_declares_in_its_body(skill, expected):
    # A declaration is a promise that the skill explains the fix for that code,
    # because build_diagnostic points a reader at the skill by name. Require the
    # code to appear in the prose below the frontmatter, so a skill cannot claim
    # a code it never mentions. Scoped to this family for the same reason as the
    # tests above: the seed skill predates the rule and other passes land later.
    text = pack.read_pack_text(pack.SKILLS_DIR, skill, pack.SKILL_FILE)
    # Strip leading blank lines first so the split lands on the closing fence,
    # not the opening one. If a file gained a leading newline, `\n---\n` would
    # first match the opening fence and pull the whole frontmatter (the declared
    # codes) into `body`, passing the check vacuously.
    _, _, body = text.lstrip().partition("\n---\n")
    assert body, f"{skill} has no body below its frontmatter"

    missing = [code for code in expected if code not in body]
    assert not missing, (
        f"{skill} declares {missing} but never names them below its frontmatter"
    )


# The event-driven/CQRS element family (#1553). The eight skills that teach a
# coded fix pin to their exact declared codes; the one that teaches none
# (`query`) pins to an empty list, mirroring the workflow/refactor/analysis
# family's tests above. Scoped to this family's own skills for the same reason.
_EVENT_CQRS_CODE_TEACHING_SKILLS = {
    "event-sourced-aggregate": ["ES_AGGREGATE_NO_EVENTS", "ES_EVENT_MISSING_APPLY"],
    "projection": [
        "PROJECTION_WITHOUT_PROJECTOR",
        "UNSOURCED_PROJECTION_FIELD",
        "USAGE_NOT_A_PROJECTION",
    ],
    "projector": ["PROJECTOR_HANDLES_ORPHANED_EVENT"],
    "query-handler": ["QUERY_HANDLER_WITHOUT_QUERY"],
    "subscriber": ["SUBSCRIBER_NO_STREAMS"],
    "upcaster": ["UPCASTER_GAP"],
    "process-manager": ["PROCESS_MANAGER_UNCLOSED"],
    "message-enrichment": ["USAGE_ENRICHER_NOT_CALLABLE"],
}

_EVENT_CQRS_NO_CODE_SKILLS = ["query"]


@pytest.mark.parametrize(
    ("skill", "expected"), sorted(_EVENT_CQRS_CODE_TEACHING_SKILLS.items())
)
def test_event_cqrs_skill_declares_its_exact_codes(skill, expected):
    # Pin each code-teaching skill in this family to the exact list it
    # declares, so dropping or mistyping a code in its frontmatter reds here
    # rather than slipping through the "is a real DiagnosticCode" check above.
    assert pack.skill_diagnostic_codes(skill) == expected


@pytest.mark.parametrize("skill", _EVENT_CQRS_NO_CODE_SKILLS)
def test_event_cqrs_skill_that_teaches_no_code_declares_none(skill):
    assert pack.skill_diagnostic_codes(skill) == []


@pytest.mark.parametrize(
    ("skill", "expected"), sorted(_EVENT_CQRS_CODE_TEACHING_SKILLS.items())
)
def test_event_cqrs_skill_names_every_code_it_declares_in_its_body(skill, expected):
    # A declaration is a promise that the skill explains the fix for that
    # code. Require the code to appear in the prose below the frontmatter, so
    # a skill cannot claim a code it never mentions.
    text = pack.read_pack_text(pack.SKILLS_DIR, skill, pack.SKILL_FILE)
    # Strip leading blank lines first so the split lands on the closing fence,
    # not the opening one. If a file gained a leading newline, `\n---\n` would
    # first match the opening fence and pull the whole frontmatter (the declared
    # codes) into `body`, passing the check vacuously.
    _, _, body = text.lstrip().partition("\n---\n")
    assert body, f"{skill} has no body below its frontmatter"

    missing = [code for code in expected if code not in body]
    assert not missing, (
        f"{skill} declares {missing} but never names them below its frontmatter"
    )


# The building-block element family. The six skills that teach a coded
# fix pin to their exact declared codes; the six that teach none pin to an empty
# list, mirroring the two families above. Scoped to this family's own skills for
# the same reason: the other passes own the rest and must not collide here.
_BUILDING_BLOCK_CODE_TEACHING_SKILLS = {
    "aggregate": [
        "AGGREGATE_NOT_NOUN",
        "AGGREGATE_NO_INVARIANTS",
        "AGGREGATE_TOO_LARGE",
        "AGGREGATE_WITHOUT_COMMAND_HANDLER",
        "CROSS_AGGREGATE_REFERENCE",
    ],
    "value-object": ["VALUE_OBJECT_MUTABLE_FIELD", "VALUE_OBJECT_INVARIANT_FAILED"],
    "command": ["COMMAND_NOT_IMPERATIVE", "UNUSED_COMMAND"],
    "event": [
        "EVENT_NOT_PAST_TENSE",
        "EVENT_WITHOUT_DATA",
        "UNRAISED_EVENT",
        "UNHANDLED_EVENT",
    ],
    "command-handler": [
        "COMMAND_HANDLER_CROSS_CLUSTER",
        "HANDLER_TOO_BROAD",
        "HANDLER_PERSISTS_AND_CALLS_OUT",
    ],
    "event-handler": [
        "EVENT_HANDLER_FOREIGN_EVENT",
        "HANDLER_TOO_BROAD",
        "HANDLER_PERSISTS_AND_CALLS_OUT",
    ],
}

_BUILDING_BLOCK_NO_CODE_SKILLS = [
    "entity",
    "application-service",
    "domain-service",
    "repository",
    "api-endpoint",
    "custom-validator",
]

# The twelve skills the family covers, written out independently of the two lists
# above. Without it, dropping a skill from both lists would leave the partition
# check happy and the skill pinned by nothing.
_BUILDING_BLOCK_FAMILY_SKILLS = frozenset(
    {
        "aggregate",
        "api-endpoint",
        "application-service",
        "command",
        "command-handler",
        "custom-validator",
        "domain-service",
        "entity",
        "event",
        "event-handler",
        "repository",
        "value-object",
    }
)


def test_building_block_family_lists_partition_real_skills():
    # The two family lists are hand-maintained. Guard that they stay a clean
    # partition of the twelve: no skill in both, no duplicates, every skill in the
    # family named by exactly one list, and every named skill a real pack skill.
    code_teaching = list(_BUILDING_BLOCK_CODE_TEACHING_SKILLS)
    named = code_teaching + _BUILDING_BLOCK_NO_CODE_SKILLS

    assert set(code_teaching).isdisjoint(_BUILDING_BLOCK_NO_CODE_SKILLS)
    assert len(named) == len(set(named)), "a skill is listed twice"
    assert set(named) == _BUILDING_BLOCK_FAMILY_SKILLS, (
        "the two lists no longer cover exactly the twelve family skills"
    )
    assert set(pack.iter_skills()) >= _BUILDING_BLOCK_FAMILY_SKILLS, (
        "a named skill is not in the pack"
    )


@pytest.mark.parametrize(
    ("skill", "expected"), sorted(_BUILDING_BLOCK_CODE_TEACHING_SKILLS.items())
)
def test_building_block_skill_declares_its_exact_codes(skill, expected):
    # Pin each code-teaching skill in this family to the exact list it declares,
    # so dropping or mistyping a code in its frontmatter reds here rather than
    # slipping through the "is a real DiagnosticCode" check above.
    assert pack.skill_diagnostic_codes(skill) == expected


@pytest.mark.parametrize("skill", _BUILDING_BLOCK_NO_CODE_SKILLS)
def test_building_block_skill_that_teaches_no_code_declares_none(skill):
    # The building-block skills with no coded convention (DiagnosticCode has no
    # ENTITY_*, REPOSITORY_*, or service codes) declare nothing. Pin the negative
    # direction so a stray declaration on one of them is caught.
    assert pack.skill_diagnostic_codes(skill) == []


@pytest.mark.parametrize(
    ("skill", "expected"), sorted(_BUILDING_BLOCK_CODE_TEACHING_SKILLS.items())
)
def test_building_block_skill_names_every_code_it_declares_in_its_body(skill, expected):
    # A declaration is a promise that the skill explains the fix for that code.
    # Require the code to appear in the prose below the frontmatter, so a skill
    # cannot claim a code it never mentions.
    text = pack.read_pack_text(pack.SKILLS_DIR, skill, pack.SKILL_FILE)
    # Strip leading blank lines first so the split lands on the closing fence,
    # not the opening one. If a file gained a leading newline, `\n---\n` would
    # first match the opening fence and pull the whole frontmatter (the declared
    # codes) into `body`, passing the check vacuously.
    _, _, body = text.lstrip().partition("\n---\n")
    assert body, f"{skill} has no body below its frontmatter"

    missing = [code for code in expected if code not in body]
    assert not missing, (
        f"{skill} declares {missing} but never names them below its frontmatter"
    )


_BUILDING_BLOCK_SKILL_CODE_PAIRS = sorted(
    (skill, code)
    for skill, codes in _BUILDING_BLOCK_CODE_TEACHING_SKILLS.items()
    for code in codes
)


@pytest.mark.parametrize(("skill", "code"), _BUILDING_BLOCK_SKILL_CODE_PAIRS)
def test_building_block_code_surfaces_its_skill(skill, code):
    # The reverse contract: every code a building-block skill declares must route
    # back to that skill, both in the reverse index and on a built diagnostic.
    # This is what catches a code the builder emits for a skill that never
    # declared it (a broad command handler raising HANDLER_TOO_BROAD would land
    # the user on the event-handler skill instead of command-handler).
    assert skill in pack.diagnostic_code_skills()[code]

    diag = build_diagnostic(
        DiagnosticCode[code],
        element="my_app.Thing",
        message=f"{code} fired.",
    )
    assert skill in diag["teaching_skills"]


def test_reverse_index_maps_the_seed_code_to_the_seed_skill():
    # protean-overview declares the seed code, so it must be named. Assert
    # inclusion, not the whole list: another skill declaring the same code later
    # is the contract working, not a break. The list's own shape (sorted, no
    # duplicates) is asserted here and pinned exactly by the fake-pack tests.
    teachers = pack.diagnostic_code_skills()["AGGREGATE_NO_INVARIANTS"]

    assert "protean-overview" in teachers
    assert teachers == sorted(set(teachers))


def test_reverse_index_maps_a_family_code_to_its_skill():
    # The event-driven/CQRS family wires each skill to the codes it teaches.
    # Assert one such mapping end to end: the projection skill declares
    # PROJECTION_WITHOUT_PROJECTOR, and the reverse index names it as a teacher.
    assert "PROJECTION_WITHOUT_PROJECTOR" in pack.skill_diagnostic_codes("projection")

    teachers = pack.diagnostic_code_skills()["PROJECTION_WITHOUT_PROJECTOR"]
    assert "projection" in teachers
    assert teachers == sorted(set(teachers))


# --- Surfacing on a built diagnostic ----------------------------------------


def test_build_diagnostic_surfaces_teaching_skills():
    diag = build_diagnostic(
        DiagnosticCode.AGGREGATE_NO_INVARIANTS,
        element="my_app.Order",
        message="Order declares no invariants.",
    )

    assert "protean-overview" in diag["teaching_skills"]
    assert diag["teaching_skills"] == sorted(set(diag["teaching_skills"]))


def test_build_diagnostic_surfaces_a_family_teaching_skill():
    # A diagnostic for a code the event-driven/CQRS family declares carries the
    # teaching skill on the built diagnostic, the same way the seed code does.
    diag = build_diagnostic(
        DiagnosticCode.PROJECTION_WITHOUT_PROJECTOR,
        element="my_app.OrderSummary",
        message="OrderSummary has no projector to populate it.",
    )

    assert "projection" in diag["teaching_skills"]
    assert diag["teaching_skills"] == sorted(set(diag["teaching_skills"]))


def test_build_diagnostic_omits_teaching_skills_when_no_skill_teaches(monkeypatch):
    # Force the untaught case through the reverse index instead of hunting the
    # shipped pack for a code no skill declares: that search has no answer once
    # the pack covers every code, and the branch under test is the same either
    # way. The key must be absent entirely, mirroring resolving_operation.
    monkeypatch.setattr(
        pack, "diagnostic_code_skills", lambda: {"EVENT_WITHOUT_DATA": ["demo"]}
    )

    diag = build_diagnostic(
        DiagnosticCode.AGGREGATE_NO_INVARIANTS, element="my_app.Thing", message="msg"
    )

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


def test_metadata_block_with_no_direct_children_reads_nothing(tmp_path, monkeypatch):
    # ``metadata:`` opens with nothing indented under it before the next top-level
    # key, so the block has no direct children. There is no diagnostic_codes key
    # to find and the skill declares nothing.
    _write_skill(
        tmp_path,
        "demo",
        "---\nmetadata:\nname: demo\n---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == []


def test_block_is_read_past_a_blank_first_line_in_metadata(tmp_path, monkeypatch):
    # A blank line right after ``metadata:`` sits at the top of the block. The
    # direct-child indentation is set by the first real line past it, so the
    # diagnostic_codes key is still found.
    _write_skill(
        tmp_path,
        "demo",
        "---\nmetadata:\n\n  diagnostic_codes:\n    - AGGREGATE_NO_INVARIANTS\n---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


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


def test_block_list_skips_a_comment_line(tmp_path, monkeypatch):
    # YAML ignores a comment-only line inside a block sequence, so a comment
    # between two items does not truncate the list. The comment sits at the item
    # indentation and at column 0 to cover both shapes.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "    # the next one is the interesting case\n"
        "# and this one is unindented\n"
        "    - CROSS_AGGREGATE_REFERENCE\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "CROSS_AGGREGATE_REFERENCE",
    ]


def test_block_list_ignores_a_comment_only_item(tmp_path, monkeypatch):
    # A bare ``- # note`` is a null entry in YAML, not a code. It must not become
    # the code "# note", and it must not truncate the list: the real item after
    # it is still read. Without the fix the scanner captures "# note" verbatim.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "    - # placeholder, no code yet\n"
        "    - CROSS_AGGREGATE_REFERENCE\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "CROSS_AGGREGATE_REFERENCE",
    ]


def test_block_list_ignores_a_bare_null_item(tmp_path, monkeypatch):
    # A bare ``-`` with no value is a null entry in YAML. It must not terminate
    # the sequence: the real item after it is still read. Without the fix the
    # item regex fails to match the bare dash and the scan breaks there, dropping
    # CROSS_AGGREGATE_REFERENCE.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "    -\n"
        "    - CROSS_AGGREGATE_REFERENCE\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "CROSS_AGGREGATE_REFERENCE",
    ]


def test_inline_value_that_is_only_a_comment_reads_nothing(tmp_path, monkeypatch):
    # ``diagnostic_codes: # note`` is a null value in YAML, so the skill teaches
    # nothing. Without the fix the trailing comment is read as the code "# note".
    _write_skill(
        tmp_path,
        "demo",
        "---\nmetadata:\n  diagnostic_codes: # none yet, added later\n---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == []


def test_metadata_with_a_trailing_comment_still_opens_the_block(tmp_path, monkeypatch):
    # ``metadata: # note`` is a mapping key with a trailing comment, not an inline
    # value: the block still follows on the indented lines. Without the fix the
    # comment is read as a value, metadata is never recognized, and the codes
    # under it are missed.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata: # everything this skill teaches\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


def test_key_with_a_trailing_comment_then_block_reads_the_block(tmp_path, monkeypatch):
    # ``diagnostic_codes: # note`` followed by a block list is a comment on the
    # key line, not an inline value: the block below is the value. Without the fix
    # the comment is taken as the inline value and the block items are missed.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  diagnostic_codes: # the codes this skill teaches\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "    - CROSS_AGGREGATE_REFERENCE\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == [
        "AGGREGATE_NO_INVARIANTS",
        "CROSS_AGGREGATE_REFERENCE",
    ]


def test_metadata_block_survives_an_unindented_comment(tmp_path, monkeypatch):
    # A comment-only line at column 0 is not a top-level key, so it does not end
    # the metadata block and the key after it is still read.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  category: orientation\n"
        "# a note about the codes below\n"
        "  diagnostic_codes:\n"
        "    - AGGREGATE_NO_INVARIANTS\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


def test_metadata_key_is_found_past_an_unindented_comment(tmp_path, monkeypatch):
    # A comment-only line before the metadata key is skipped by the key scan, so
    # the block is still found.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "name: demo\n"
        "# codes this skill teaches\n"
        "metadata:\n"
        "  diagnostic_codes: [AGGREGATE_NO_INVARIANTS]\n"
        "---\n",
    )
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    assert pack.skill_diagnostic_codes("demo") == ["AGGREGATE_NO_INVARIANTS"]


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


def test_keys_with_a_space_before_the_colon_are_read(tmp_path, monkeypatch):
    # ``metadata :`` and ``diagnostic_codes :`` (a space before the colon) are
    # valid YAML: the key is still ``metadata`` / ``diagnostic_codes``. The scan
    # compares the key name with surrounding whitespace trimmed, so the codes are
    # read rather than dropped.
    _write_skill(
        tmp_path,
        "demo",
        "---\nmetadata :\n  diagnostic_codes :\n    - AGGREGATE_NO_INVARIANTS\n---\n",
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


def test_diagnostic_codes_nested_below_a_metadata_subkey_are_not_read(
    tmp_path, monkeypatch
):
    # The contract is metadata.diagnostic_codes: a direct child of metadata. A
    # diagnostic_codes key one level deeper, under a metadata sub-mapping, is
    # metadata.other.diagnostic_codes and is off-contract, so it reads as
    # "teaches nothing" rather than being swept in by matching the key name at
    # any depth.
    _write_skill(
        tmp_path,
        "demo",
        "---\n"
        "metadata:\n"
        "  other:\n"
        "    diagnostic_codes:\n"
        "      - AGGREGATE_NO_INVARIANTS\n"
        "---\n",
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


def test_skill_diagnostic_codes_raises_when_the_manifest_is_absent(
    tmp_path, monkeypatch
):
    # The single-skill accessor is a query about one named skill, so a manifest
    # it cannot read is an error, not an empty answer: unlike the reverse index,
    # it raises. This is deliberate. Pointing it at an empty pack (no such skill,
    # and no pack data) is the same missing-manifest case either way.
    monkeypatch.setattr(pack, "pack_files", lambda: tmp_path)

    with pytest.raises(FileNotFoundError):
        pack.skill_diagnostic_codes("not-a-real-skill")


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
