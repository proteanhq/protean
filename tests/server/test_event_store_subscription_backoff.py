"""An idle event-store subscription waits longer between reads, up to a cap.

The wait starts at 10 ms after the first empty read, doubles on each further
empty read up to ``max_tick_interval`` under ``[server.event_store_subscription]``
(default 1 second), and drops back to ``tick_interval`` when a read returns
messages. ``max_tick_interval = 0`` keeps the wait at ``tick_interval``.

Each test ticks the subscription by hand and reads the wait from the backoff,
so no test sleeps or measures time.
"""

import asyncio
import logging
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from protean.utils.mixins import handle
from tests.shared import MESSAGE_DB_URI

pytestmark = pytest.mark.no_test_domain

DOUBLING_TO_ONE_SECOND = [0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.0, 1.0]


class Registered(BaseEvent):
    id = Identifier()
    email = String()


class User(BaseAggregate):
    email = String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def handle_registered(self, event: Registered) -> None:
        pass


@pytest.fixture(
    params=[
        pytest.param({"provider": "memory"}, id="memory"),
        pytest.param(
            {"provider": "message_db", "database_uri": MESSAGE_DB_URI},
            id="message_db",
            marks=pytest.mark.message_db,
        ),
    ]
)
def domain(request):
    domain = Domain(name="Test")
    domain.config["event_store"] = request.param
    domain.register(User, event_sourced=True)
    domain.register(Registered, part_of=User)
    domain.register(UserEventHandler, part_of=User)
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain
        domain.event_store.store._data_reset()
        domain.event_store.store.close()


def _subscription(domain, tick_interval=0, **es_settings):
    domain.config["server"]["event_store_subscription"].update(es_settings)
    engine = Engine(domain=domain, test_mode=False)
    return EventStoreSubscription(
        engine,
        "test::user",
        UserEventHandler,
        tick_interval=tick_interval,
        enable_recovery=False,
    )


def _write_event(domain):
    user_id = str(uuid4())
    user = User(id=user_id, email="john@example.com")
    user.raise_(Registered(id=user_id, email="john@example.com"))
    domain.event_store.store.append(user._events[-1])


async def _idle_waits(sub, count):
    waits = []
    for _ in range(count):
        assert await sub.tick() is False
        waits.append(sub._next_tick_wait())
    return waits


@pytest.mark.asyncio
async def test_idle_wait_doubles_from_10ms_to_the_cap(domain):
    sub = _subscription(domain, tick_interval=0, max_tick_interval=1)

    assert await _idle_waits(sub, 9) == pytest.approx(DOUBLING_TO_ONE_SECOND)


@pytest.mark.asyncio
async def test_a_read_with_messages_resets_the_wait(domain):
    sub = _subscription(domain, tick_interval=0, max_tick_interval=1)
    await _idle_waits(sub, 9)
    assert sub._next_tick_wait() == pytest.approx(1.0)

    _write_event(domain)

    assert await sub.tick() is True
    assert sub._next_tick_wait() == 0


@pytest.mark.asyncio
async def test_unset_cap_defaults_to_one_second(domain):
    assert (
        "max_tick_interval" not in domain.config["server"]["event_store_subscription"]
    )
    sub = _subscription(domain, tick_interval=0)

    assert sub._backoff.cap == 1.0
    assert await _idle_waits(sub, 9) == pytest.approx(DOUBLING_TO_ONE_SECOND)


@pytest.mark.asyncio
async def test_zero_cap_keeps_the_wait_at_tick_interval(domain, caplog):
    caplog.set_level(logging.WARNING)
    sub = _subscription(domain, tick_interval=0.5, max_tick_interval=0)

    assert await _idle_waits(sub, 4) == [0.5, 0.5, 0.5, 0.5]
    assert "subscription.max_tick_interval_ignored" not in caplog.text


@pytest.mark.asyncio
async def test_zero_cap_with_zero_tick_interval_polls_without_waiting(domain):
    sub = _subscription(domain, tick_interval=0, max_tick_interval=0)

    assert await _idle_waits(sub, 4) == [0, 0, 0, 0]


@pytest.mark.asyncio
async def test_cap_below_tick_interval_is_ignored_with_a_warning(domain, caplog):
    caplog.set_level(logging.WARNING)
    sub = _subscription(domain, tick_interval=2, max_tick_interval=0.5)

    warnings = [
        r for r in caplog.records if r.msg == "subscription.max_tick_interval_ignored"
    ]
    assert len(warnings) == 1
    assert warnings[0].subscriber == sub.subscriber_name
    assert warnings[0].tick_interval == 2.0
    assert warnings[0].max_tick_interval == 0.5
    assert await _idle_waits(sub, 3) == [2, 2, 2]


@pytest.mark.asyncio
async def test_unset_cap_with_long_tick_interval_keeps_tick_interval(domain, caplog):
    caplog.set_level(logging.WARNING)
    sub = _subscription(domain, tick_interval=2)

    assert await _idle_waits(sub, 3) == [2, 2, 2]
    assert "subscription.max_tick_interval_ignored" not in caplog.text


@pytest.mark.asyncio
async def test_failed_position_awaiting_recovery_does_not_reset_the_wait(domain):
    sub = _subscription(domain, tick_interval=0, max_tick_interval=1)
    sub._failed_positions[1] = {
        "retry_count": 0,
        "stream_name": None,
        "stream_position": None,
    }

    assert await _idle_waits(sub, 3) == pytest.approx([0.01, 0.02, 0.04])


@pytest.mark.asyncio
async def test_reassigned_tick_interval_rebases_the_wait(domain):
    sub = _subscription(domain, tick_interval=1)
    assert sub._next_tick_wait() == 1

    sub.tick_interval = 0

    assert sub._next_tick_wait() == 0
    assert await _idle_waits(sub, 2) == pytest.approx([0.01, 0.02])


@pytest.mark.asyncio
async def test_pause_sleeps_the_backoff_wait(domain):
    sub = _subscription(domain, tick_interval=0, max_tick_interval=1)
    await _idle_waits(sub, 9)

    # The wait is 1 second, so a pause cut off at 0.3 seconds times out.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(sub._pause_between_ticks(), timeout=0.3)


@pytest.mark.asyncio
async def test_pause_in_test_mode_clamps_the_backoff_wait(domain):
    sub = _subscription(domain, tick_interval=0, max_tick_interval=1)
    sub.engine.test_mode = True
    await _idle_waits(sub, 9)
    assert sub._next_tick_wait() == pytest.approx(1.0)

    # Test mode clamps the 1-second wait to TEST_MODE_MAX_TICK_PAUSE (10 ms).
    await asyncio.wait_for(sub._pause_between_ticks(), timeout=0.3)


def test_engine_built_subscription_carries_the_configured_cap(domain):
    domain.config["server"]["event_store_subscription"]["max_tick_interval"] = 4
    engine = Engine(domain=domain, test_mode=False)

    subscriptions = [
        sub
        for sub in engine.subscriptions.values()
        if isinstance(sub, EventStoreSubscription)
    ]
    assert subscriptions
    for sub in subscriptions:
        assert sub._backoff.cap == 4.0
