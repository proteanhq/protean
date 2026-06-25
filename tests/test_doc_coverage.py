"""
Doc-coverage gate: every public ``@domain.*`` element type must be documented.

For each member of ``DomainObjects`` this asserts there is either a building-block
concept page (``docs/concepts/building-blocks/<plural>.md``) or an API reference page
(``docs/api/<singular>.md``). Known gaps live in ``ALLOWLIST`` with a reason, so a NEW
undocumented element fails CI while existing gaps stay visible and get burned down.

This is the framework-side complement to the skills repo's element→skill drift guard:
it keeps Protean's own docs in sync with the element types it ships.
"""

from pathlib import Path

from protean.utils import DomainObjects

_ROOT = Path(__file__).resolve().parents[1]
_BUILDING_BLOCKS = _ROOT / "docs" / "concepts" / "building-blocks"
_API = _ROOT / "docs" / "api"

# Element types currently/intentionally without a dedicated building-block or API page,
# each with its reason. Burn these down (write the page, drop the entry) over time.
ALLOWLIST = {
    "EMAIL": "Infrastructure/adapter element, not a domain building block; documented "
    "(if at all) under adapters rather than building-blocks/API.",
    "EVENT_SOURCED_REPOSITORY": "Covered in the event-sourcing / repositories docs; "
    "no standalone page.",
}


def _kebab(element: DomainObjects) -> str:
    """AGGREGATE -> aggregate, COMMAND_HANDLER -> command-handler."""
    return element.name.lower().replace("_", "-")


def _plural(singular: str) -> str:
    """Naive pluralization matching the building-blocks filenames (y -> ies)."""
    return singular[:-1] + "ies" if singular.endswith("y") else singular + "s"


def _is_documented(element: DomainObjects) -> bool:
    singular = _kebab(element)
    return (_BUILDING_BLOCKS / f"{_plural(singular)}.md").exists() or (
        _API / f"{singular}.md"
    ).exists()


def test_every_element_type_is_documented_or_allowlisted():
    missing = []
    for element in DomainObjects:
        if element.name in ALLOWLIST:
            continue
        if not _is_documented(element):
            missing.append(element.name)

    assert not missing, (
        "Protean element type(s) with no building-block or API doc page: "
        f"{sorted(missing)}.\nAdd docs/concepts/building-blocks/<plural>.md or "
        "docs/api/<singular>.md, or add the element to ALLOWLIST with a reason."
    )


def test_allowlist_entries_are_current_elements():
    """Keep the allowlist honest: drop entries for renamed/removed element types."""
    valid = {e.name for e in DomainObjects}
    stale = sorted(name for name in ALLOWLIST if name not in valid)
    assert not stale, (
        f"ALLOWLIST references element type(s) no longer in DomainObjects: {stale}."
    )
