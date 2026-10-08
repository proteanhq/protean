"""The ``AGENTS.md`` negative-constraint generator.

The pack must render exactly one hard rule per error-level diagnostic code,
derived from the live registry so adding or removing an error code changes the
file. These tests couple the output to ``REGISTRY`` filtered by level, exclude
the advisory codes, and pin the concrete shape of one rendered rule.
"""

from __future__ import annotations

import re

from protean.ir.diagnostics import REGISTRY, DiagnosticCode
from protean.ir.generators.agents import generate_agents_md

# A rendered rule ends with its diagnostic code in backticked parentheses:
# ``... (`CONFIG_AMBIGUOUS_ELEMENT_NAME`)``.
_CODE_ANCHOR = re.compile(r"\(`([A-Z_]+)`\)")


def _error_codes() -> set[str]:
    """The code strings the pack must render: the error-level codes, live."""
    return {code.value for code, meta in REGISTRY.items() if meta.level == "error"}


def test_one_constraint_per_error_level_code():
    """The set of rendered codes equals the live error-level code set.

    This is the acceptance coupling: adding or removing an error code changes
    the file. It rides the live registry, not a literal list copied here.
    """
    expected = _error_codes()
    # Non-vacuous: the registry actually has error-level codes to render.
    assert expected, "expected at least one error-level diagnostic code"

    out = generate_agents_md(version="9.9.9")
    rendered = set(_CODE_ANCHOR.findall(out))

    assert rendered == expected


def test_advisory_codes_are_excluded():
    """Warning/info codes are hard-excluded: only error-level codes are rules.

    Names a known warning code and a known info code and asserts neither its
    code nor its ``meaning`` text appears, so the level filter is real (not just
    a happy accident of which codes exist).
    """
    out = generate_agents_md(version="9.9.9")

    info_meta = REGISTRY[DiagnosticCode.AGGREGATE_NOT_NOUN]  # level == "info"
    warning_meta = REGISTRY[DiagnosticCode.ADAPTER_CALL_IN_DOMAIN]  # level == "warning"
    assert info_meta.level == "info"
    assert warning_meta.level == "warning"

    assert DiagnosticCode.AGGREGATE_NOT_NOUN.value not in out
    assert DiagnosticCode.ADAPTER_CALL_IN_DOMAIN.value not in out
    # The meaning text of an excluded code must not leak in either, so a future
    # severity flip into "error" is caught by the coupling test above.
    assert info_meta.meaning not in out
    assert warning_meta.meaning not in out


def test_rule_renders_meaning_rationale_and_fix_verbatim():
    """One rule is pinned to its exact literal shape.

    This golden is written out by hand, independent of the generator's format
    string, so a change to the "Do not ... To comply: ..." template is caught
    even if the generator and a derived expectation drifted together.
    """
    out = generate_agents_md(version="9.9.9")

    expected = (
        "- **Do not** write code that causes this error: The event store is "
        "used before the domain is initialized. The event store is wired during "
        "`domain.init()`; using it before then leaves the store unset. To "
        "comply: Call `domain.init()` before using the event store. "
        "(`CONFIG_EVENT_STORE_NOT_INITIALIZED`)"
    )
    assert expected in out


def test_every_rule_carries_its_registry_meaning_rationale_and_fix():
    """Each error code's meaning, rationale, and fix all appear in its rule.

    Guards against a template that drops one of the three registry fields.
    """
    out = generate_agents_md(version="9.9.9")

    checked = 0
    for code, meta in REGISTRY.items():
        if meta.level != "error":
            continue
        checked += 1
        assert meta.meaning in out, f"{code.value} meaning missing"
        assert meta.rationale in out, f"{code.value} rationale missing"
        assert meta.fix in out, f"{code.value} fix missing"
    # Non-vacuous: an all-advisory registry would skip the loop body entirely.
    assert checked, "expected at least one error-level diagnostic code"


def test_version_is_stamped_in_the_header():
    """The version string appears in the H1 header."""
    out = generate_agents_md(version="1.2.3")
    assert out.startswith("# Protean 1.2.3\n")


def test_deterministic_for_the_same_version():
    """Two calls for the same version are byte-identical."""
    first = generate_agents_md(version="9.9.9")
    second = generate_agents_md(version="9.9.9")
    assert first == second
    # Non-vacuous: the pack actually rendered rules.
    assert "## Do not break these rules" in first
    assert first.count("- **Do not** ") == len(_error_codes())


def test_codes_render_in_sorted_order():
    """Rules render sorted by code name, regardless of registry order."""
    out = generate_agents_md(version="9.9.9")
    rendered = _CODE_ANCHOR.findall(out)
    assert rendered == sorted(rendered)
    # Non-vacuous: more than one code, so the ordering claim has teeth.
    assert len(rendered) > 1
