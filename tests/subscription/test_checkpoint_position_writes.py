"""Position-write decisions in the event-store subscription checkpoint path.

``update_read_position`` persists the durable checkpoint only once the configured
interval is reached; ``update_current_position_to_store`` persists only when the
store is actually behind the in-memory cursor. The gap-safety and read-position
suites exercise these indirectly through ``tick``; here they are pinned directly
so a wrong comparison or off-by-one on the checkpoint cadence is caught (an
under-persisting checkpoint replays more work after a crash, an over-persisting
one writes a redundant record every tick).
"""

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier
from protean.server import Engine
from protean.utils import Processing, fqn
from protean.utils.mixins import handle


class Pinged(BaseEvent):
    id = Identifier()


class Thing(BaseAggregate):
    @apply
    def on_pinged(self, event: Pinged) -> None:
        pass


class ThingHandler(BaseEventHandler):
    @handle(Pinged)
    def on_pinged(self, event: Pinged) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["event_processing"] = Processing.ASYNC.value
    test_domain.register(Thing, event_sourced=True)
    test_domain.register(Pinged, part_of=Thing)
    test_domain.register(ThingHandler, part_of=Thing)
    test_domain.init(traverse=False)


@pytest.fixture
def subscription(test_domain):
    engine = Engine(test_domain, test_mode=True)
    return engine._subscriptions[fqn(ThingHandler)]


@pytest.mark.asyncio
async def test_read_position_persists_exactly_at_the_interval(
    subscription, monkeypatch
):
    """The durable write fires on the tick that *reaches* the interval, not one
    before or after, and the counter resets afterwards."""
    sub = subscription
    sub.position_update_interval = 3
    sub.current_position = -1
    sub.messages_since_last_position_write = 0

    written: list[int] = []
    original_write = sub.write_position

    async def record_write(position):
        written.append(position)
        # Delegate to the real writer so the counter reset it performs is exercised.
        return await original_write(position)

    monkeypatch.setattr(sub, "write_position", record_write)

    # Two consumed positions: still below the interval, nothing persisted yet.
    assert await sub.update_read_position(10) == 10
    assert await sub.update_read_position(11) == 11
    assert sub.current_position == 11  # cursor advances on every call
    assert written == []

    # The third consumed position reaches the interval → persist, at that position.
    assert await sub.update_read_position(12) == 12
    assert written == [12]

    # Counter reset by the write: the next two are again below the interval, the
    # third crosses it again.
    await sub.update_read_position(13)
    await sub.update_read_position(14)
    assert written == [12]
    await sub.update_read_position(15)
    assert written == [12, 15]


@pytest.mark.asyncio
async def test_current_position_persisted_only_when_store_is_behind(
    subscription, monkeypatch
):
    """``update_current_position_to_store`` writes only when the store's last
    written position is strictly behind the cursor, and returns that last written
    position (not the cursor)."""
    sub = subscription
    sub.current_position = 5

    written: list[int] = []

    async def record_write(position):
        written.append(position)
        return position

    monkeypatch.setattr(sub, "write_position", record_write)

    # Store already at the cursor (5 == 5): nothing to write; the last written
    # position (5) is returned.
    async def at_5():
        return 5

    monkeypatch.setattr(sub, "fetch_last_position", at_5)
    assert await sub.update_current_position_to_store() == 5
    assert written == []

    # Store behind the cursor (3 < 5): persist the cursor, still returning the
    # last written position (3), not the cursor.
    async def at_3():
        return 3

    monkeypatch.setattr(sub, "fetch_last_position", at_3)
    assert await sub.update_current_position_to_store() == 3
    assert written == [5]
