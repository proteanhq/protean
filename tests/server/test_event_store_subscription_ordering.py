"""Order of the calls ``EventStoreSubscription`` makes per message and per position.

``process_batch`` and ``run_recovery_pass`` interleave handler calls, trace
records, durable failure records and cursor writes in the order
``specs/Recovery.tla`` models. These tests record every step into one list and
pin that order, so a change that reorders two awaited calls goes red.
"""

from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
    FailedPositionStatus,
)
from protean.utils import recovery_trace
from protean.utils.eventing import EventStoreMeta, Message, Metadata
from protean.utils.mixins import handle


class Registered(BaseEvent):
    id = Identifier()
    name = String()


class User(BaseAggregate):
    name = String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.name = event.name


class NameCheckingHandler(BaseEventHandler):
    """Fails for a user named ``bad`` and succeeds for every other name."""

    @handle(Registered)
    def handle_registered(self, event):
        if event.name == "bad":
            raise RuntimeError("handler failure")


class _RecordingEngine(Engine):
    """Engine that appends each ``handle_message`` call to ``steps``."""

    steps: list[dict]

    async def handle_message(self, handler_cls, message, worker_id=None):
        self.steps.append(
            {
                "action": "handle",
                "position": message.metadata.event_store.global_position,
            }
        )
        return await super().handle_message(handler_cls, message, worker_id)


class _RecordingSubscription(EventStoreSubscription):
    """Subscription that appends each cursor write and status write to ``steps``."""

    steps: list[dict]

    async def update_read_position(self, position: int) -> int:
        self.steps.append({"action": "cursor_write", "position": position})
        return await super().update_read_position(position)

    async def _write_recovery_status(self, position, status, retry_count, **kwargs):
        self.steps.append({"action": f"status:{status.value}", "position": position})
        await super()._write_recovery_status(position, status, retry_count, **kwargs)


class _ActiveIdempotencyStore:
    """Idempotency store stub that reports every key as already processed."""

    @property
    def is_active(self) -> bool:
        return True

    def check(self, idempotency_key: str) -> dict:
        return {"status": "success"}

    def record_success(self, idempotency_key: str, value: bool) -> None:
        pass


@pytest.fixture
def register(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(NameCheckingHandler, part_of=User)
    test_domain.init(traverse=False)
    return test_domain


def _message(
    global_position: int,
    name: str = "good",
    asynchronous: bool = True,
    idempotency_key: str | None = None,
) -> Message:
    user_id = str(uuid4())
    user = User(id=user_id, name=name)
    user.raise_(Registered(id=user_id, name=name))
    message = Message.from_domain_object(user._events[-1])
    metadata_dict = message.metadata.to_dict()
    metadata_dict["event_store"] = EventStoreMeta(
        position=0, global_position=global_position
    )
    metadata_dict["domain"]["asynchronous"] = asynchronous
    metadata_dict["headers"]["stream"] = f"test-{user_id}"
    if idempotency_key is not None:
        metadata_dict["headers"]["idempotency_key"] = idempotency_key
    message.metadata = Metadata(**metadata_dict)
    return message


def _write_event(test_domain, msg: Message) -> None:
    test_domain.event_store._adapter.write_message(
        msg.metadata.headers.stream,
        msg.metadata.headers.type,
        msg.data,
        metadata=msg.metadata.to_dict(),
    )


def _subscription(test_domain, steps: list, **kwargs) -> _RecordingSubscription:
    engine = _RecordingEngine(domain=test_domain, test_mode=False)
    engine.steps = steps
    options = {
        "messages_per_tick": 10,
        "position_update_interval": 100,
        "max_retries": 3,
        "enable_recovery": True,
        "recovery_interval_seconds": 0,
        "retry_delay_seconds": 0,
    }
    options.update(kwargs)
    subscription = _RecordingSubscription(
        engine, "test", NameCheckingHandler, **options
    )
    subscription.steps = steps
    return subscription


def _actions(steps: list[dict]) -> list[tuple[str, int]]:
    return [(step["action"], step["position"]) for step in steps]


@pytest.mark.asyncio
async def test_failed_message_is_recorded_before_the_cursor_moves(register):
    with recovery_trace.capture() as steps:
        sub = _subscription(register, steps)
        result = await sub.process_batch([_message(1, name="bad")])

    assert result == 0
    assert _actions(steps) == [
        ("handle", 1),
        ("fail", 1),
        ("record", 1),
        ("advance", 1),
        ("cursor_write", 1),
    ]


@pytest.mark.asyncio
async def test_failed_message_without_recovery_advances_with_no_record(register):
    with recovery_trace.capture() as steps:
        sub = _subscription(register, steps, enable_recovery=False)
        result = await sub.process_batch([_message(1, name="bad")])

    assert result == 0
    assert _actions(steps) == [
        ("handle", 1),
        ("fail", 1),
        ("advance", 1),
        ("cursor_write", 1),
    ]


@pytest.mark.asyncio
async def test_batch_handles_each_message_and_moves_the_cursor_in_order(register):
    with recovery_trace.capture() as steps:
        sub = _subscription(register, steps)
        result = await sub.process_batch(
            [_message(1), _message(2, name="bad"), _message(3)]
        )

    assert result == 2
    assert _actions(steps) == [
        ("handle", 1),
        ("handle_ok", 1),
        ("cursor_write", 1),
        ("handle", 2),
        ("fail", 2),
        ("record", 2),
        ("advance", 2),
        ("cursor_write", 2),
        ("handle", 3),
        ("handle_ok", 3),
        ("cursor_write", 3),
    ]


@pytest.mark.asyncio
async def test_inline_message_moves_the_cursor_without_a_handler_call(register):
    with recovery_trace.capture() as steps:
        sub = _subscription(register, steps)
        result = await sub.process_batch([_message(1, asynchronous=False)])

    # An inline message is skipped and not counted as handled.
    assert result == 0
    assert _actions(steps) == [("handle_ok", 1), ("cursor_write", 1)]


@pytest.mark.asyncio
async def test_idempotent_skip_moves_the_cursor_and_counts_as_handled(
    register, monkeypatch
):
    with recovery_trace.capture() as steps:
        sub = _subscription(register, steps)
        monkeypatch.setattr(
            sub.engine.domain, "_idempotency_store", _ActiveIdempotencyStore()
        )
        result = await sub.process_batch([_message(1, idempotency_key="key-1")])

    assert result == 1
    assert _actions(steps) == [("handle_ok", 1), ("cursor_write", 1)]


@pytest.mark.asyncio
async def test_recovery_pass_works_through_positions_in_order(register):
    """Position 1 is past ``max_retries``, position 2 now succeeds, and
    position 3 still fails."""
    exhausted, resolved, failing = (
        _message(1, name="good"),
        _message(2, name="good"),
        _message(3, name="bad"),
    )
    for msg in (exhausted, resolved, failing):
        _write_event(register, msg)

    with recovery_trace.capture() as steps:
        sub = _subscription(register, steps, max_retries=2)
        sub._failed_positions = {
            msg.metadata.event_store.global_position: {
                "retry_count": retry_count,
                "stream_name": msg.metadata.headers.stream,
                "stream_position": 0,
            }
            for msg, retry_count in ((exhausted, 2), (resolved, 0), (failing, 0))
        }
        recovered = await sub.run_recovery_pass()

    assert recovered == 1
    assert _actions(steps) == [
        (f"status:{FailedPositionStatus.EXHAUSTED.value}", 1),
        ("recover", 1),
        ("handle", 2),
        (f"status:{FailedPositionStatus.RESOLVED.value}", 2),
        ("recover", 2),
        ("handle", 3),
        ("record", 3),
    ]
    assert [step.get("delivered") for step in steps if step["action"] == "recover"] == [
        False,
        True,
    ]
    assert sub._failed_positions == {
        3: {
            "retry_count": 1,
            "stream_name": failing.metadata.headers.stream,
            "stream_position": 0,
        }
    }
