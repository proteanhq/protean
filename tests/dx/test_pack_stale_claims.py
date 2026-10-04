"""The DX pack does not bring back errors that once repeated across its skills.

Each rule below names one error that used to appear in several skills: the old
``protean.globals`` import path, calls into the private ``_dao``, links to docs
pages that do not exist, and the claim that a string ``part_of`` is rejected on a
handler or repository. The test reads every text file in the pack and fails on
any line that matches a rule, except the lines a rule allows on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean import dx

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the scan reads files by path",
        allow_module_level=True,
    )

# A string part_of resolves at init on every element, so no skill may say a
# handler or repository rejects it. Each alternative names part_of, a string
# reference, or a handler or repository, so text about other APIs passes.
_STRING_PART_OF_REJECTED = re.compile(
    r"part_of\b.*\bnot\s+(a\s+)?string\b"
    r"|do(es)?\s+(\*\*)?not(\*\*)?\s+accept\s+a\s+string\s+(`?part_of|reference)"
    r"|string\s+reference\b[^.]{0,60}\bnot\s+accepted"
    r"|(handlers?|repositor(y|ies))\s+requires?\s+the\s+resolved\s+class",
    re.IGNORECASE,
)

# (name, pattern, lines allowed to match as "path:line")
RULES: list[tuple[str, re.Pattern[str], frozenset[str]]] = [
    ("the protean.globals import path", re.compile(r"protean\.globals"), frozenset()),
    (
        "the private _dao",
        re.compile(r"\b_dao\b"),
        # The one place that names the DAO and says when infrastructure code
        # may use it.
        frozenset({"skills/repository/references/custom-queries.md:23"}),
    ),
    (
        "a docs page that does not exist",
        re.compile(r"readthedocs|patterns/(cqrs|event-sourcing)"),
        frozenset(),
    ),
    ("a string part_of called invalid", _STRING_PART_OF_REJECTED, frozenset()),
]


def find_stale_claims(label: str, text: str) -> list[str]:
    """Return ``"<label>:<line>: <rule>"`` for every line that breaks a rule."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        location = f"{label}:{number}"
        for name, pattern, allowed in RULES:
            if pattern.search(line) and location not in allowed:
                found.append(f"{location}: {name}")
    return found


def test_the_pack_holds_none_of_the_stale_claims():
    files = sorted(
        path for path in PACK_ROOT.rglob("*") if path.suffix in {".md", ".py"}
    )
    assert len(files) > 200, f"scanned only {len(files)} files"

    problems = []
    for path in files:
        label = path.relative_to(PACK_ROOT).as_posix()
        problems.extend(find_stale_claims(label, path.read_text(encoding="utf-8")))

    assert problems == []


# --- The rules on lines the pack used to hold ---------------------------------


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ("from protean.globals import current_domain", "protean.globals"),
        ("order = repo._dao.find_by(order_id=event.order_id)", "_dao"),
        ("See https://protean.readthedocs.io/en/latest/", "does not exist"),
        ("[CQRS](https://docs.proteanhq.com/patterns/cqrs/)", "does not exist"),
        ("- Use `part_of=AggregateClass` (class reference, not string)", "part_of"),
        ("Note: `part_of=User` uses the class reference (not a string).", "part_of"),
        (
            (
                "event handlers do **not** accept a string `part_of` "
                "(it raises at registration)"
            ),
            "part_of",
        ),
        ("unlike handlers, they do not accept a string reference.", "part_of"),
        (
            (
                'a string reference (`part_of="Order"`) is not accepted and raises '
                "an error at registration"
            ),
            "part_of",
        ),
        ("repositories require the resolved class", "part_of"),
    ],
)
def test_a_stale_line_is_reported(line, rule):
    found = find_stale_claims("skills/x/SKILL.md", line)

    assert len(found) == 1
    assert found[0].startswith("skills/x/SKILL.md:1: ")
    assert rule in found[0]


@pytest.mark.parametrize(
    "line",
    [
        "from protean import current_domain",
        "order = repo.find_by(order_id=event.order_id)",
        "dao = domain.providers.get_dao(Order)",
        "[CQRS](https://docs.proteanhq.com/concepts/architecture/cqrs/)",
        'A string, `part_of="AggregateName"`, also works and resolves at `init`',
        "anything else is rejected at registration with `IncorrectUsageError`.",
        "The value is not a string, so the field raises `ValidationError`.",
        "A handler with no `@handle` method raises at registration.",
        "The serializer does not accept a string for `amount`.",
        "A `HasMany` field requires the resolved class of its entity.",
    ],
)
def test_a_current_line_passes(line):
    assert find_stale_claims("skills/x/SKILL.md", line) == []


def test_an_allowed_line_passes_only_at_its_own_location():
    line = "`self._dao` remains available as an internal escape hatch"

    assert (
        find_stale_claims(
            "skills/repository/references/custom-queries.md", ("\n" * 22 + line)
        )
        == []
    )
    assert find_stale_claims("skills/repository/SKILL.md", line) == [
        "skills/repository/SKILL.md:1: the private _dao"
    ]
