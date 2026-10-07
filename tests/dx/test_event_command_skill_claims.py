"""The event and command skills keep the fixes that made their examples correct.

The snippet runner proves each block runs. It cannot see a block that runs but
teaches the wrong thing: an event raised from ``__init__``, a hand-written
snapshot event, a version number in an event's class name, or an upcaster with
no ``@domain.upcaster`` decorator. These tests read the seven skills' Python
blocks and assets and fail when one of those comes back.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from protean import dx
from tests.support.snippets import extract_blocks

pytestmark = pytest.mark.no_test_domain

SKILLS_ROOT = Path(str(dx.pack_files())) / dx.SKILLS_DIR

if not SKILLS_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the scan reads skills by path",
        allow_module_level=True,
    )

SKILLS = (
    "event",
    "command",
    "add-event",
    "add-command",
    "add-use-case",
    "event-sourced-aggregate",
    "upcaster",
)


def runnable_sources(skill: str) -> list[tuple[str, str]]:
    """Return ``(label, source)`` for every runnable block and asset of ``skill``.

    Blocks marked ``# fragment`` are left out: they hold wrong examples shown
    on purpose.
    """
    root = SKILLS_ROOT / skill
    sources = []
    for path in sorted(root.rglob("*.md")):
        for block in extract_blocks(path.read_text(encoding="utf-8")):
            if not block.fragment:
                label = f"{path.relative_to(SKILLS_ROOT)}:{block.line}"
                sources.append((label, block.source))
    sources.extend(
        (str(path.relative_to(SKILLS_ROOT)), path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("assets/*.py"))
    )
    return sources


def parsed_classes(skill: str) -> list[tuple[str, ast.ClassDef]]:
    classes = []
    for label, source in runnable_sources(skill):
        tree = ast.parse(source)
        classes.extend(
            (label, node) for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
        )
    return classes


def decorator_names(node: ast.ClassDef) -> list[str]:
    """Return ``"domain.event"`` style names for the class's decorators."""
    names = []
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        names.append(ast.unparse(target))
    return names


def init_methods_that_raise_events(classes) -> list[str]:
    found = []
    for label, node in classes:
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                calls = [
                    call
                    for call in ast.walk(item)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "raise_"
                ]
                if calls:
                    found.append(f"{label}: {node.name}.__init__")
    return found


def test_every_skill_has_runnable_code():
    for skill in SKILLS:
        assert parsed_classes(skill), skill


@pytest.mark.parametrize("skill", SKILLS)
def test_no_example_raises_an_event_from_init(skill):
    assert init_methods_that_raise_events(parsed_classes(skill)) == []


def test_the_init_scan_finds_an_init_that_raises():
    tree = ast.parse(
        "class Customer:\n"
        "    def __init__(self, **kwargs):\n"
        "        super().__init__(**kwargs)\n"
        "        self.raise_(CustomerRegistered(id=self.id))\n"
    )
    classes = [("x.md:1", node) for node in tree.body]
    assert init_methods_that_raise_events(classes) == ["x.md:1: Customer.__init__"]


def test_no_event_class_carries_a_version_in_its_name():
    events = [
        (label, node.name)
        for label, node in parsed_classes("event")
        if "domain.event" in decorator_names(node)
    ]
    assert events
    versioned = [
        f"{label}: {name}" for label, name in events if re.search(r"V\d", name)
    ]
    assert versioned == []


@pytest.mark.parametrize("skill", ["event", "upcaster"])
def test_every_runnable_upcaster_is_registered(skill):
    upcasters = [
        (label, node)
        for label, node in parsed_classes(skill)
        if any(ast.unparse(base) == "BaseUpcaster" for base in node.bases)
    ]
    assert upcasters
    unregistered = [
        f"{label}: {node.name}"
        for label, node in upcasters
        if "domain.upcaster" not in decorator_names(node)
    ]
    assert unregistered == []


def test_the_event_skill_shows_generated_fact_events():
    text = (SKILLS_ROOT / "event" / "SKILL.md").read_text(encoding="utf-8")
    assert "fact_events=True" in text
    assert "OrderFactEvent" in text
    assert "Snapshot" not in text


def test_the_event_skill_says_event_sourced_aggregates_raise_first():
    text = (SKILLS_ROOT / "event" / "SKILL.md").read_text(encoding="utf-8")
    assert (
        "The business method raises the event, and an `@apply` method changes "
        "the state." in text
    )


def test_the_event_sourced_skill_keeps_rules_13_and_14():
    text = (SKILLS_ROOT / "event-sourced-aggregate" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "13. **A failed handler writes no events**" in text
    assert "14. **`reserved=[...]` names removed fields**" in text
