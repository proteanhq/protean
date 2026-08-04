"""Every decorator option must appear in the decorator reference.

`docs/reference/domain-elements/element-decorators.md` is the one place that
claims to list what each decorator accepts, and a batch of options had reached
the code without reaching it. Some were explained in guides, none had a row in
the reference, so a reader checking "what can I pass here?" got a wrong answer
from the page whose whole job is that question.

Options come from each element's `_default_options`, and the internal ones from
`_internal_options`, so nothing is enumerated here. That is deliberate: a list
in this file would be a third place to keep in step, and it would go stale the
same way the page did. A new option fails this test the day it is added.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.domain_service import BaseDomainService
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.core.subscriber import BaseSubscriber
from protean.core.value_object import BaseValueObject

# These read a markdown file and static class metadata. Nothing here needs a
# domain, so skip the autouse fixture that builds one per test.
pytestmark = pytest.mark.no_test_domain

REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "reference"
    / "domain-elements"
    / "element-decorators.md"
)

ELEMENTS = {
    "aggregate": BaseAggregate,
    "entity": BaseEntity,
    "value_object": BaseValueObject,
    "event": BaseEvent,
    "command": BaseCommand,
    "query": BaseQuery,
    "event_handler": BaseEventHandler,
    "command_handler": BaseCommandHandler,
    "query_handler": BaseQueryHandler,
    "application_service": BaseApplicationService,
    "domain_service": BaseDomainService,
    "projection": BaseProjection,
    "projector": BaseProjector,
    "process_manager": BaseProcessManager,
    "subscriber": BaseSubscriber,
}

# Options the framework sets for itself. Listing them in a reference of what a
# user may pass would be noise. `_internal_options` is read from each class
# rather than repeated here, so marking an option internal in the code is enough.
NOT_USER_FACING = {
    "aggregate_cluster",  # set by the framework while resolving the cluster
    "part_of",  # documented per element as required, not as an option row
}


def _user_facing_options(cls: type) -> set[str]:
    internal = set(getattr(cls, "_internal_options", frozenset()))
    return {name for name, _ in cls._default_options} - internal - NOT_USER_FACING


@pytest.fixture(scope="module")
def reference_text() -> str:
    assert REFERENCE.is_file(), f"{REFERENCE} is missing"
    text = REFERENCE.read_text(encoding="utf-8")
    assert text, f"{REFERENCE} is empty"
    return text


def _documented(text: str) -> set[str]:
    """Option names the page mentions anywhere a reader would find them.

    Table rows and headings are the normal case. Inline code spans count too,
    because a deprecated option such as `is_event_sourced` is documented in a
    warning admonition rather than given a row of its own, and that is the right
    shape for it.
    """
    names = set(re.findall(r"^\|\s*\*{0,2}`(\w+)`\*{0,2}\s*\|", text, re.M))
    names |= set(re.findall(r"^#{2,4}\s*`(\w+)`\s*$", text, re.M))
    names |= set(re.findall(r"`(\w+)`", text))
    return names


class TestEveryOptionIsInTheReference:
    def test_the_page_parses(self, reference_text):
        assert len(_documented(reference_text)) > 20, (
            "parsed suspiciously few option names; the table format changed"
        )

    @pytest.mark.parametrize("element", sorted(ELEMENTS))
    def test_element_options_are_documented(self, reference_text, element):
        options = _user_facing_options(ELEMENTS[element])
        assert options, f"no options read for {element}; `_default_options` moved"
        missing = sorted(options - _documented(reference_text))
        assert not missing, (
            f"`@domain.{element}` accepts these options, but they appear nowhere "
            f"in {REFERENCE.name}: {missing}. Add a row to that element's table, "
            "or to 'Options every element accepts' if every decorator takes it."
        )
