"""How the custom-validator skill describes a chain of field validators.

A field's ``validators=[...]`` run in list order, and validation stops at the
first one that fails. Empty values skip the validators. The skill must say
so, and must not claim that every validator runs and the errors are
collected.

``tests/dx/test_plugin.py`` only checks that the render matches the pack, so
a pack edit that brings back the "errors are collected" claim would keep it
green. The text tests below check the claim itself. The behavior tests pin
the documented behavior to the field pipeline, so a change to collect errors
fails here and forces the skill to change with it.
"""

# No ``from __future__ import annotations``: the aggregates below name local
# validator instances in their field annotations, which must resolve when the
# class is built.
import re
from pathlib import Path

import pytest

from protean import dx
from protean.dx.pack import REFERENCES_DIR as REFERENCES_DIRNAME
from protean.exceptions import ValidationError
from protean.fields import String

SKILL_DIR = Path(str(dx.pack_files())) / dx.SKILLS_DIR / "custom-validator"
SKILL_MD = SKILL_DIR / "SKILL.md"
COMPOSING = SKILL_DIR / REFERENCES_DIRNAME / "composing-validators.md"

COLLECTING_CLAIM = re.compile(
    r"errors are collected|errors from each are collected|run independently"
    r"|all validation errors at once|error collection|all validators run",
    re.IGNORECASE,
)
FIRST_FAILURE = re.compile(r"stops at the first fail", re.IGNORECASE)


@pytest.mark.no_test_domain
def test_no_custom_validator_file_claims_errors_are_collected() -> None:
    files = sorted(p for p in SKILL_DIR.rglob("*") if p.suffix in {".md", ".py"})
    assert files
    for path in files:
        match = COLLECTING_CLAIM.search(path.read_text())
        assert match is None, f"{path}: {match.group(0) if match else ''}"


@pytest.mark.no_test_domain
@pytest.mark.parametrize("path", [SKILL_MD, COMPOSING], ids=lambda p: p.name)
def test_file_says_validation_stops_at_the_first_failure(path: Path) -> None:
    assert FIRST_FAILURE.search(path.read_text()), path


@pytest.mark.no_test_domain
@pytest.mark.parametrize(
    "claim",
    [
        "all validators run, errors are collected.",
        "All validators run, and errors from each are collected.",
        "Validators run independently",
        "the user gets all validation errors at once",
        "## Error Collection",
    ],
)
def test_collecting_claim_pattern_catches_known_wordings(claim: str) -> None:
    assert COLLECTING_CLAIM.search(claim)


@pytest.mark.no_test_domain
def test_collecting_claim_pattern_passes_the_current_wording() -> None:
    text = (
        "Validators run in list order, and validation stops at the first "
        "failing validator. Later validators do not run."
    )
    assert not COLLECTING_CLAIM.search(text)


class _Rejects:
    """A validator that always fails and records each call."""

    def __init__(self, message: str) -> None:
        self.error = message
        self.calls: list[object] = []

    def __call__(self, value: object) -> None:
        self.calls.append(value)
        raise ValidationError(self.error)


class _RejectsValue:
    """A validator that fails only for one value."""

    def __init__(self, bad: str, message: str) -> None:
        self.bad = bad
        self.error = message

    def __call__(self, value: object) -> None:
        if value == self.bad:
            raise ValidationError(self.error)


def test_only_the_first_failing_validator_reports(test_domain) -> None:
    first = _Rejects("first rule")
    second = _Rejects("second rule")

    @test_domain.aggregate
    class Account:
        name: String(validators=[first, second])

    test_domain.init(traverse=False)

    with pytest.raises(ValidationError) as exc:
        Account(name="anything")

    assert exc.value.messages["name"] == ["first rule"]
    assert first.calls == ["anything"]
    assert second.calls == []


def test_later_validator_runs_when_the_first_passes(test_domain) -> None:
    first = _RejectsValue("bad-for-first", "first rule")
    second = _RejectsValue("bad-for-second", "second rule")

    @test_domain.aggregate
    class Account:
        name: String(validators=[first, second])

    test_domain.init(traverse=False)

    with pytest.raises(ValidationError) as exc:
        Account(name="bad-for-second")

    assert exc.value.messages["name"] == ["second rule"]


def test_empty_value_skips_every_validator(test_domain) -> None:
    first = _Rejects("first rule")
    second = _Rejects("second rule")

    @test_domain.aggregate
    class Account:
        name: String(validators=[first, second])

    test_domain.init(traverse=False)

    account = Account()

    assert account.name is None
    assert first.calls == []
    assert second.calls == []
