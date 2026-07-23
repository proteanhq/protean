"""Gap-safe checkpointing for a ``$all`` (cross-category) subscription.

``global_position`` is a store-wide sequence assigned when a row is inserted and
made visible when its transaction commits. Within a category, writes are
serialized (a per-category lock), so a category's own values also become visible
in ascending order. Across categories they can commit out of order — a lower
position committing after a higher one — so a ``$all`` subscription that advances
past the highest position seen would silently skip the late-committing lower one. The subscription
holds at the first gap (a low-watermark), and abandons a gap that stays unfilled
longer than ``gap_timeout_seconds`` (a rolled-back append leaves a permanent
hole). These tests exercise the low-watermark directly (``_gap_safe_batch``) and
end-to-end through ``tick`` with a simulated gapped read. The real cross-category
out-of-order commit that produces a gap is a property of a concurrent Postgres
``bigserial`` store, not the (single-threaded) memory store, so it is simulated
here by controlling the read; that store behaviour was confirmed separately.
"""

import time
from types import SimpleNamespace

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.utils import Processing, fqn
from protean.utils.mixins import handle


class Pinged(BaseEvent):
    id = Identifier()


class Thing(BaseAggregate):
    name = String()

    @apply
    def on_pinged(self, event: Pinged) -> None:
        pass


class AllHandler(BaseEventHandler):
    @handle(Pinged)
    def on_pinged(self, event: Pinged) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(Thing, is_event_sourced=True)
    test_domain.register(Pinged, part_of=Thing)
    test_domain.register(AllHandler, stream_category="$all")
    test_domain.init(traverse=False)


@pytest.fixture
def all_subscription(test_domain):
    engine = Engine(test_domain, test_mode=True)
    return engine._subscriptions[fqn(AllHandler)]


def _msg(global_position: int):
    """A minimal stand-in carrying only the attribute ``_gap_safe_batch`` reads."""
    return SimpleNamespace(
        metadata=SimpleNamespace(
            event_store=SimpleNamespace(global_position=global_position)
        )
    )


def _positions(messages):
    return [m.metadata.event_store.global_position for m in messages]


class TestGapSafeBatch:
    def test_contiguous_batch_is_returned_whole(self, all_subscription):
        sub = all_subscription
        sub.current_position = 0

        out = sub._gap_safe_batch([_msg(1), _msg(2), _msg(3)])

        assert _positions(out) == [1, 2, 3]
        assert sub._gap_first_seen == {}

    def test_fresh_subscription_does_not_treat_position_zero_as_a_gap(
        self, all_subscription
    ):
        """global_position is 1-based, so a fresh subscription (current == -1)
        must consume position 1, not stall waiting for a phantom position 0."""
        sub = all_subscription
        assert sub.current_position == -1

        out = sub._gap_safe_batch([_msg(1), _msg(2)])

        assert _positions(out) == [1, 2]
        assert sub._gap_first_seen == {}

    def test_holds_at_the_first_gap(self, all_subscription):
        sub = all_subscription
        sub.current_position = 0

        # Position 2 is missing (uncommitted); 3 has committed above it.
        out = sub._gap_safe_batch([_msg(1), _msg(3)])

        # Only the contiguous prefix (1) is released; 3 is held behind the gap.
        assert _positions(out) == [1]
        assert 2 in sub._gap_first_seen

    def test_resumes_contiguously_when_the_gap_fills(self, all_subscription):
        sub = all_subscription
        sub.current_position = 0

        sub._gap_safe_batch([_msg(1), _msg(3)])  # hold; record gap at 2
        sub.current_position = 1  # 1 was processed

        out = sub._gap_safe_batch([_msg(2), _msg(3)])  # 2 has now committed

        assert _positions(out) == [2, 3]
        assert sub._gap_first_seen == {}

    def test_abandons_a_gap_after_the_timeout(self, all_subscription):
        sub = all_subscription
        sub.current_position = 0
        sub.gap_timeout_seconds = 5
        # The gap at 2 was first seen well beyond the timeout (a rolled-back
        # append that will never commit).
        sub._gap_first_seen = {2: time.monotonic() - 10}

        out = sub._gap_safe_batch([_msg(1), _msg(3)])

        # 2 is abandoned, so 3 is released past it.
        assert _positions(out) == [1, 3]
        assert sub._gap_first_seen == {}

    def test_abandoned_hole_sets_watermark_past_itself_without_a_message(
        self, all_subscription
    ):
        """A hole abandoned below a still-held gap sets the watermark past itself
        even though no message accompanies it — ``tick`` then advances the cursor,
        so the subscription does not re-read and re-abandon it every tick (a stall
        on a rolled-back multi-event append)."""
        sub = all_subscription
        sub.current_position = 1
        sub.gap_timeout_seconds = 5
        # Hole 2 timed out; hole 3 not yet; position 4 present.
        sub._gap_first_seen = {2: time.monotonic() - 10}

        out = sub._gap_safe_batch([_msg(4)])

        assert out == []  # 4 is held behind the not-yet-timed-out gap at 3
        assert sub._gap_watermark == 2  # watermark stepped past the abandoned hole 2
        assert 3 in sub._gap_first_seen  # still waiting on 3
        assert 2 not in sub._gap_first_seen

    def test_abandons_consecutive_holes_and_resumes(self, all_subscription):
        sub = all_subscription
        sub.current_position = 1
        sub.gap_timeout_seconds = 5
        old = time.monotonic() - 10
        sub._gap_first_seen = {2: old, 3: old}  # a rolled-back 2-event append

        out = sub._gap_safe_batch([_msg(4)])

        assert _positions(out) == [4]  # both holes abandoned, 4 released in order
        assert sub._gap_watermark == 4
        assert sub._gap_first_seen == {}

    def test_held_gap_timer_is_not_reset_across_ticks(self, all_subscription):
        """A gap that stays open ages monotonically — its first-seen time is not
        reset each tick, so it does time out after gap_timeout_seconds."""
        sub = all_subscription
        sub.current_position = 0

        sub._gap_safe_batch([_msg(1), _msg(3)])  # records the gap at 2
        first_seen = sub._gap_first_seen[2]

        sub._gap_safe_batch([_msg(3)])  # 2 still missing on the next tick

        assert sub._gap_first_seen[2] == first_seen  # not reset

    def test_does_not_abandon_before_the_timeout(self, all_subscription):
        sub = all_subscription
        sub.current_position = 0
        sub.gap_timeout_seconds = 60
        # Gap at 2 seen just now — nowhere near the timeout.
        sub._gap_first_seen = {2: time.monotonic()}

        out = sub._gap_safe_batch([_msg(1), _msg(3)])

        assert _positions(out) == [1]  # still holding 3
        assert 2 in sub._gap_first_seen

    def test_empty_batch_clears_gap_state(self, all_subscription):
        sub = all_subscription
        sub._gap_first_seen = {2: time.monotonic()}

        out = sub._gap_safe_batch([])

        assert out == []
        assert sub._gap_first_seen == {}

    def test_gap_timeout_default_is_five_seconds(self, all_subscription):
        assert all_subscription.gap_timeout_seconds == 5


@pytest.mark.asyncio
async def test_get_next_batch_applies_gap_safety_for_all(all_subscription, monkeypatch):
    """``get_next_batch_of_messages`` routes a ``$all`` read through the
    low-watermark, so a gapped read is held at the gap."""
    sub = all_subscription
    sub.current_position = 0

    def fake_read(stream_name, position, no_of_messages):
        assert stream_name == "$all"
        return [_msg(1), _msg(3)]  # 2 is missing

    monkeypatch.setattr(sub.store, "read", fake_read)

    batch = await sub.get_next_batch_of_messages()

    assert _positions(batch) == [1]  # held behind the gap at 2
    assert 2 in sub._gap_first_seen


@pytest.mark.asyncio
async def test_get_next_batch_does_not_gate_a_single_category(
    all_subscription, monkeypatch
):
    """Only ``$all`` is gated. A single category is gapless by construction — the
    store assigns global_position in commit order within a category (MessageDB's
    per-category advisory write lock; the single-threaded memory store) — so its
    reads never carry a gap and must not be gated. The gapped ``[1, 3]`` below is
    an artificial input purely to prove the gate: a real category read cannot
    produce it."""
    sub = all_subscription
    sub.stream_category = "thing"  # a specific category, not $all
    sub.current_position = 0

    monkeypatch.setattr(
        sub.store,
        "read",
        lambda stream_name, position, no_of_messages: [_msg(1), _msg(3)],
    )

    batch = await sub.get_next_batch_of_messages()

    assert _positions(batch) == [1, 3]  # returned whole; the gap logic never runs
    assert sub._gap_first_seen == {}


@pytest.mark.asyncio
async def test_tick_holds_at_gap_then_resumes_in_order(
    all_subscription, test_domain, monkeypatch
):
    """End-to-end through ``tick``: with a lower global_position missing from the
    read (a concurrent out-of-order commit), the subscription processes only up
    to the gap and holds; once the gap commits it processes the rest in order,
    never skipping the late-committing lower position.

    The gap is simulated by controlling what ``store.read`` returns (the memory
    store assigns global_position contiguously, so it cannot produce a real
    cross-category gap — that behaviour is a property of a concurrent Postgres
    ``bigserial`` store, confirmed separately). The events themselves are real.
    """
    sub = all_subscription

    # Three real events at global_positions 1, 2, 3.
    thing = Thing(id="t1", name="thing")
    for _ in range(3):
        thing.raise_(Pinged(id="t1"))
        test_domain.event_store.store.append(thing._events[-1])
    events = test_domain.event_store.store.read("$all")
    assert [e.metadata.event_store.global_position for e in events] == [1, 2, 3]

    # Record every position the subscription consumes (advances past), which is
    # the gap-safety observable regardless of sync/async dispatch.
    consumed: list[int] = []
    original_update = sub.update_read_position

    async def record(position):
        consumed.append(position)
        return await original_update(position)

    monkeypatch.setattr(sub, "update_read_position", record)

    # Tick 1: position 2 has not committed yet — read returns [1, 3].
    monkeypatch.setattr(sub.store, "read", lambda *a, **k: [events[0], events[2]])
    await sub.tick()

    assert consumed == [1]  # held behind the gap at 2; 3 not consumed
    assert sub.current_position == 1

    # Tick 2: position 2 has now committed — read returns [2, 3].
    monkeypatch.setattr(sub.store, "read", lambda *a, **k: [events[1], events[2]])
    await sub.tick()

    assert consumed == [1, 2, 3]  # resumes in order, nothing skipped
    assert sub.current_position == 3


@pytest.mark.asyncio
async def test_durable_position_is_not_written_past_a_gap(
    all_subscription, test_domain, monkeypatch
):
    """Crash-safety: the durable checkpoint must not advance past an unfilled gap,
    so a resume re-reads from before it rather than skipping the late commit."""
    sub = all_subscription
    sub.position_update_interval = 1  # persist on every consumed position

    thing = Thing(id="t1", name="thing")
    for _ in range(3):
        thing.raise_(Pinged(id="t1"))
        test_domain.event_store.store.append(thing._events[-1])
    events = test_domain.event_store.store.read("$all")

    # Position 2 is missing — the subscription processes 1 and holds.
    monkeypatch.setattr(sub.store, "read", lambda *a, **k: [events[0], events[2]])
    await sub.tick()

    # Durable position is 1 (before the gap), not 3.
    assert await sub.fetch_last_position() == 1


@pytest.mark.asyncio
async def test_tick_steps_over_an_abandoned_gap_with_no_message(
    all_subscription, monkeypatch
):
    """An abandoned hole with no message below the next held gap advances the
    cursor through ``tick`` (the returned batch is empty, so ``process_batch``
    cannot) — this is what breaks the stall on a rolled-back multi-event append."""
    sub = all_subscription
    sub.current_position = 1
    sub.gap_timeout_seconds = 5
    sub._gap_first_seen = {2: time.monotonic() - 10}  # hole 2 timed out
    # Read exposes only position 4: hole 2 (timed out) and hole 3 (still held).
    monkeypatch.setattr(sub.store, "read", lambda *a, **k: [_msg(4)])

    await sub.tick()

    assert sub.current_position == 2  # stepped past abandoned hole 2, held at 3
    assert 3 in sub._gap_first_seen


@pytest.mark.asyncio
async def test_tick_does_not_advance_past_unprocessed_messages_on_interruption(
    all_subscription, test_domain, monkeypatch
):
    """Crash-safety: if ``process_batch`` is interrupted mid-batch, the cursor must
    stay at the last position actually processed — never jump to the watermark —
    so the unprocessed tail is re-read, not skipped."""
    sub = all_subscription

    thing = Thing(id="t1", name="thing")
    for _ in range(3):
        thing.raise_(Pinged(id="t1"))
        test_domain.event_store.store.append(thing._events[-1])
    events = test_domain.event_store.store.read("$all")  # positions 1, 2, 3

    monkeypatch.setattr(sub.store, "read", lambda *a, **k: list(events))

    # Fail the second position update, simulating a transient write/Redis error
    # partway through the batch.
    original = sub.update_read_position
    seen: list[int] = []

    async def failing_update(position):
        seen.append(position)
        if len(seen) == 2:
            raise RuntimeError("simulated mid-batch failure")
        return await original(position)

    monkeypatch.setattr(sub, "update_read_position", failing_update)

    with pytest.raises(RuntimeError):
        await sub.tick()

    # Only position 1 was fully processed; the cursor did not jump to the
    # watermark (3), so positions 2 and 3 will be re-read on the next tick.
    assert sub.current_position == 1
