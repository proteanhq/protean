"""Domain models, Hypothesis strategies, and settings backing the correctness
property suite (:issue:`#1251`).

The suite machine-checks guarantees the framework claims, over randomized
histories rather than single reproductions:

* **Replay** — reconstructing an event-sourced aggregate from its stream matches
  an *independent* fold of that stream (``expected_state`` below), so a wrong
  ``@apply`` handler is caught rather than compared against itself. See
  ``test_replay_determinism``.
* **Checkpoint never skips a committed event** — see ``test_checkpoint_no_skip``,
  a stateful model rather than a ``@given`` over these aggregate models.

These models run against their own ``verification_domain`` (activated once per
module by ``conftest.py``), so every test module here is ``no_test_domain``.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Domain
from protean.fields import Identifier, Integer, String
from protean.server import Engine
from protean.utils import Processing, fqn
from protean.utils.mixins import handle

# A property test builds and folds many aggregates per example, which has
# variable latency; a wall-clock deadline would flake under CI load. Ordering /
# correctness are what the properties assert, never timing.
property_settings = settings(
    deadline=None,
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)


class Created(BaseEvent):
    counter_id = Identifier(required=True)
    name = String(max_length=50, required=True)


class Incremented(BaseEvent):
    counter_id = Identifier(required=True)
    by = Integer(required=True)


class Renamed(BaseEvent):
    counter_id = Identifier(required=True)
    name = String(max_length=50, required=True)


class Counter(BaseAggregate):
    """An event-sourced aggregate whose whole state is a fold of its events, so
    a replayed stream and a live-built instance are directly comparable."""

    name = String(max_length=50)
    value = Integer(default=0)

    @classmethod
    def create(cls, counter_id: str, name: str) -> Counter:
        counter = cls(id=counter_id, name=name)
        counter.raise_(Created(counter_id=counter_id, name=name))
        return counter

    def increment(self, by: int) -> None:
        self.raise_(Incremented(counter_id=self.id, by=by))

    def rename(self, name: str) -> None:
        self.raise_(Renamed(counter_id=self.id, name=name))

    @apply
    def on_created(self, event: Created) -> None:
        self.id = event.counter_id
        self.name = event.name
        self.value = 0

    @apply
    def on_incremented(self, event: Incremented) -> None:
        self.value += event.by

    @apply
    def on_renamed(self, event: Renamed) -> None:
        self.name = event.name


class AllEvents(BaseEventHandler):
    """An ``$all`` subscriber — the cross-category shape whose checkpointing the
    no-skip property exercises. The handler body is irrelevant; the property
    drives ``_gap_safe_batch`` and the cursor, not the handler."""

    @handle(Created)
    def on_created(self, event: Created) -> None:
        pass  # pragma: no cover — never invoked; the property drives the cursor


verification_domain = Domain(name="Verification")
verification_domain.config["event_processing"] = Processing.ASYNC.value
verification_domain.register(Counter, event_sourced=True)
verification_domain.register(Created, part_of=Counter)
verification_domain.register(Incremented, part_of=Counter)
verification_domain.register(Renamed, part_of=Counter)
verification_domain.register(AllEvents, stream_category="$all")
verification_domain.init(traverse=False)


def build_all_subscription():
    """A fresh ``$all`` ``EventStoreSubscription`` from the verification domain.

    ``_gap_safe_batch`` is pure over ``current_position`` / ``_gap_first_seen`` /
    ``_gap_watermark`` and never touches the store, so the checkpoint property can
    drive it directly without the async engine loop.
    """
    with verification_domain.domain_context():
        engine = Engine(verification_domain, test_mode=True)
    return engine._subscriptions[fqn(AllEvents)]


# Printable ASCII minus the three characters ``String`` HTML-escapes (``& < >``).
# Escaping is length-changing (``&`` -> ``&amp;``), so an escapable char near the
# 50-char limit would overflow ``max_length`` on assignment — an orthogonal
# String-sanitizer concern, not a replay-determinism one. Excluding them keeps
# sanitization a no-op so this strategy exercises replay, not field validation.
_names = st.text(
    alphabet=st.characters(
        min_codepoint=32, max_codepoint=126, exclude_characters="&<>"
    ),
    min_size=1,
    max_size=50,
)


@st.composite
def counter_histories(draw: st.DrawFn) -> list[BaseEvent]:
    """A valid Counter history: a ``Created`` followed by any number of
    ``Incremented`` / ``Renamed`` events, all sharing one id."""
    counter_id = str(uuid4())
    events: list[BaseEvent] = [Created(counter_id=counter_id, name=draw(_names))]
    for _ in range(draw(st.integers(min_value=0, max_value=12))):
        if draw(st.booleans()):
            events.append(
                Incremented(counter_id=counter_id, by=draw(st.integers(-1000, 1000)))
            )
        else:
            events.append(Renamed(counter_id=counter_id, name=draw(_names)))
    return events


def expected_state(events: list[BaseEvent]) -> dict:
    """A pure-Python fold of a Counter history — the replay oracle.

    Deliberately independent of ``Counter``'s ``@apply`` handlers: ``from_events``
    is compared against *this*, not against another path through the same
    handlers, so a broken handler (e.g. a rename dropped) is caught.
    """
    name = ""
    value = 0
    for event in events:
        if isinstance(event, Created):
            name, value = event.name, 0
        elif isinstance(event, Incremented):
            value += event.by
        else:  # Renamed — histories hold only these three event types
            name = event.name
    return {"name": name, "value": value}


def live_build(events: list[BaseEvent]) -> Counter:
    """Build a Counter through its command methods (create, then increment /
    rename) — the path a user's code drives, distinct from ``from_events``."""
    created = events[0]
    counter = Counter.create(counter_id=created.counter_id, name=created.name)
    for event in events[1:]:
        if isinstance(event, Incremented):
            counter.increment(event.by)
        else:
            counter.rename(event.name)
    return counter


def message_at(global_position: int):
    """A minimal stand-in carrying only the attribute the subscription's
    gap-safe read inspects (``metadata.event_store.global_position``)."""
    return SimpleNamespace(
        metadata=SimpleNamespace(
            event_store=SimpleNamespace(global_position=global_position)
        )
    )
