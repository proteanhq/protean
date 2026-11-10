"""Find the capability flags that no conformance test is gated on.

A conformance test names the flags it needs with ``@pytest.mark.requires(...)``
or ``@pytest.mark.requires_any(...)``. :func:`untested_flags` lists the
single-bit members of a port's ``Flag`` type that no marker in a suite names,
so a flag an adapter can declare is never left without a test.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import Flag
from pathlib import Path
from typing import TypeVar

import pytest

CAPABILITY_MARKERS = ("requires", "requires_any")

FlagT = TypeVar("FlagT", bound=Flag)


def marked_flags(item: pytest.Item) -> list[Flag]:
    """Return every flag the item's ``requires`` and ``requires_any`` markers name.

    A composite flag passed to a marker, such as a named tier, is returned as
    it is and is not split into its bits.
    """
    return [
        flag
        for name in CAPABILITY_MARKERS
        for marker in item.iter_markers(name)
        for flag in marker.args
    ]


def collect_items(session: pytest.Session, path: Path) -> list[pytest.Item]:
    """Collect the test items of the ``test_*.py`` file or folder at ``path``.

    The items are collected under ``session``, the running test session, and
    are not run.
    """
    files = [path] if path.is_file() else sorted(path.rglob("test_*.py"))
    items: list[pytest.Item] = []
    for file in files:
        items.extend(_items_under(pytest.Module.from_parent(session, path=file)))
    return items


def _items_under(node: pytest.Item | pytest.Collector) -> list[pytest.Item]:
    if isinstance(node, pytest.Item):
        return [node]
    return [item for child in node.collect() for item in _items_under(child)]


def untested_flags(flag_type: type[FlagT], items: Iterable[pytest.Item]) -> list[FlagT]:
    """Return the single-bit members of ``flag_type`` that no item's marker names.

    Composite members, such as a named tier, are left out: they are sets of
    other members, not capabilities of their own. The result keeps the order
    in which ``flag_type`` defines its members.
    """
    named = {flag for item in items for flag in marked_flags(item)}
    return [
        member
        for member in flag_type.__members__.values()
        if _is_single_bit(member) and member not in named
    ]


def _is_single_bit(member: Flag) -> bool:
    value = member.value
    return isinstance(value, int) and value > 0 and value & (value - 1) == 0
