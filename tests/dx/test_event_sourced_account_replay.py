"""The ``Account`` example in the event-sourced-aggregate skill replays to the same state.

The skill's first example defines an event-sourced ``Account`` whose
``AccountOpened`` event carries ``account_id`` and ``owner_name``. Replay
through ``Account.from_events()`` starts from a blank aggregate and rebuilds
state only through the ``@apply`` methods, so the ``opened()`` handler has to
set every field the event carries, plus ``status``. If it sets only part of
that state, the live aggregate and the replayed one differ.

The snippet guard (``tests/dx/test_skill_snippets.py``) only checks that the
blocks run. This test runs the shipped example, opens an account, rebuilds it
from its own events and compares the two. The negative test puts back the old
``opened()`` body, which set only ``status``, and shows the comparison catches
it.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import protean
import protean.fields
from protean import Domain, dx
from tests.support.snippets import extract_blocks

# The test builds its own Domain from the skill's code, so skip the autouse
# test_domain fixture.
pytestmark = pytest.mark.no_test_domain

SKILL_FILE = (
    Path(str(dx.pack_files())) / dx.SKILLS_DIR / "event-sourced-aggregate" / "SKILL.md"
)

FULL_OPENED = """\
    @apply
    def opened(self, event: AccountOpened):
        self.account_id = event.account_id
        self.owner_name = event.owner_name
        self.status = "ACTIVE"
"""

STATUS_ONLY_OPENED = """\
    @apply
    def opened(self, event: AccountOpened):
        self.status = "ACTIVE"
"""


def _account_source() -> str:
    """Return the skill's runnable blocks up to and including the one that defines ``Account``."""
    sources = []
    for block in extract_blocks(SKILL_FILE.read_text(encoding="utf-8")):
        if block.fragment:
            continue
        sources.append(block.source)
        if "class Account:" in block.source:
            return "\n".join(sources)
    raise AssertionError(f"no block in {SKILL_FILE} defines `class Account`")


def _open_and_replay(source: str, monkeypatch: pytest.MonkeyPatch):
    """Run ``source``, open an account, and rebuild it from its events."""
    # Run the code as a real module: Protean and Pydantic look a class's module
    # up in ``sys.modules``.
    module = types.ModuleType("_event_sourced_account_replay")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    namespace = module.__dict__
    namespace["__file__"] = str(SKILL_FILE)
    for name in protean.__all__:
        namespace[name] = getattr(protean, name)
    for name in protean.fields.__all__:
        namespace[name] = getattr(protean.fields, name)
    namespace["domain"] = Domain(name="EventSourcedAccountReplay")
    # `dont_inherit` keeps this module's `from __future__ import annotations`
    # out of the example: Protean reads field annotations as live objects.
    exec(compile(source, str(SKILL_FILE), "exec", dont_inherit=True), namespace)

    # The example may bind its own `domain`, so read it back after the run.
    domain = namespace["domain"]
    account_cls = namespace["Account"]
    domain.init(traverse=False)

    with domain.domain_context():
        original = account_cls.open(account_id="ACC-001", owner_name="Alice")
        events = list(original._events)
        assert events, "Account.open() must raise at least one event"
        replayed = account_cls.from_events(events)
    return original, replayed


def test_replayed_account_matches_the_original(monkeypatch):
    original, replayed = _open_and_replay(_account_source(), monkeypatch)

    assert (original.account_id, original.owner_name, original.status) == (
        "ACC-001",
        "Alice",
        "ACTIVE",
    )
    assert replayed.account_id == original.account_id
    assert replayed.owner_name == original.owner_name
    assert replayed.status == original.status


def test_status_only_opened_handler_loses_owner_name_on_replay(monkeypatch):
    source = _account_source()
    assert FULL_OPENED in source, "the skill's opened() handler no longer matches"
    broken = source.replace(FULL_OPENED, STATUS_ONLY_OPENED)
    assert broken != source

    original, replayed = _open_and_replay(broken, monkeypatch)

    assert original.owner_name == "Alice"
    assert replayed.owner_name != original.owner_name
