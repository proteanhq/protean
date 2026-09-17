"""Tests for operator replay/purge of an exhausted event-store position.

Covers ``EventStoreSubscription.replay_exhausted`` and ``purge_exhausted``:

- Replay re-invokes the handler exactly once and, on success, resolves the
  position so it stops being listed as exhausted.
- Replay that fails again reopens the position with a fresh ``Failed`` record,
  so a rebuild tracks it instead of dropping it as ``Exhausted``.
- Replay never moves the subscription read cursor.
- Purge appends a terminal ``Purged`` marker: the position drops out of the
  rebuilt set, the history is kept, and the purge survives a rebuild.
"""

import asyncio
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.engine import CommandDispatcher
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
    FailedPositionStatus,
    reconstruct_unresolved,
    write_recovery_status_record,
)
from protean.utils.dlq import collect_failed_streams
from protean.utils.eventing import EventStoreMeta, Message, Metadata
from protean.utils.mixins import handle

MAX_RETRIES = 2


# ──────────────────────────────────────────────────────────────────────
# Domain elements
# ──────────────────────────────────────────────────────────────────────


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class User(BaseAggregate):
    email = String()
    name = String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name


class ToggleHandler(BaseEventHandler):
    """Fails while ``should_fail`` is set; counts every invocation."""

    should_fail = True
    calls = 0

    @handle(Registered)
    def handle_registered(self, event):
        type(self).calls += 1
        if type(self).should_fail:
            raise RuntimeError("boom")


class Order(BaseAggregate):
    total = String()


class PlaceOrder(BaseCommand):
    total = String()


class ToggleCommandHandler(BaseCommandHandler):
    """Command handler that fails while ``should_fail`` is set."""

    should_fail = True
    calls = 0

    @handle(PlaceOrder)
    def place(self, command):
        type(self).calls += 1
        if type(self).should_fail:
            raise RuntimeError("boom")


# ──────────────────────────────────────────────────────────────────────
# Fixtures and helpers
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_toggle():
    ToggleHandler.should_fail = True
    ToggleHandler.calls = 0


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ToggleHandler, part_of=User)
    test_domain.init(traverse=False)


def _make_message(global_position: int = 1, stream_position: int = 0) -> Message:
    """Build a Registered event message pinned to a known stream location."""
    user_id = str(uuid4())
    stream_name = f"test-{user_id}"
    user = User(id=user_id, email="test@example.com", name="Test")
    user.raise_(Registered(id=user_id, email="test@example.com", name="Test"))

    message = Message.from_domain_object(user._events[-1])
    metadata_dict = message.metadata.to_dict()
    metadata_dict["event_store"] = EventStoreMeta(
        position=stream_position, global_position=global_position
    )
    metadata_dict["domain"]["asynchronous"] = True
    if metadata_dict.get("headers"):
        metadata_dict["headers"]["stream"] = stream_name
    else:
        metadata_dict["headers"] = {"stream": stream_name}
    message.metadata = Metadata(**metadata_dict)
    return message


def _write_event_to_store(test_domain, msg: Message) -> None:
    test_domain.event_store.store._write(
        msg.metadata.headers.stream,
        msg.metadata.headers.type,
        msg.data,
        metadata=msg.metadata.to_dict(),
    )


def _subscription(test_domain) -> EventStoreSubscription:
    engine = Engine(domain=test_domain, test_mode=False)
    return EventStoreSubscription(
        engine,
        User.meta_.stream_category,
        ToggleHandler,
        messages_per_tick=10,
        position_update_interval=1,
        max_retries=MAX_RETRIES,
        enable_recovery=True,
        recovery_interval_seconds=0,
        retry_delay_seconds=0,
    )


def _drive_to_exhaustion(sub: EventStoreSubscription, msg: Message) -> None:
    """Process the message once, then run recovery past ``max_retries``."""

    async def drive() -> None:
        await sub.process_batch([msg])
        for _ in range(MAX_RETRIES + 1):
            await sub.run_recovery_pass()

    asyncio.run(drive())


def _exhausted_record(sub: EventStoreSubscription, position: int) -> Message:
    """Return the Exhausted record for ``position`` on the subscription's stream."""
    for message in sub.store.read_all(sub.failed_positions_stream):
        if message.data.get("position") != position:
            continue
        headers = message.metadata.headers if message.metadata else None
        if headers and headers.type == FailedPositionStatus.EXHAUSTED.value:
            return message
    raise AssertionError(f"No Exhausted record found for position {position}")


def _latest_status(sub: EventStoreSubscription, position: int) -> str | None:
    """Return the last-written status for ``position`` (last-status-wins)."""
    status: str | None = None
    for message in sub.store.read_all(sub.failed_positions_stream):
        if message.data.get("position") != position:
            continue
        headers = message.metadata.headers if message.metadata else None
        if headers and headers.type:
            status = headers.type
    return status


def _rebuild(sub: EventStoreSubscription) -> dict[int, dict]:
    """Reconstruct the unresolved set the way a restart (and recover) would."""
    unresolved, _watermark, _read = reconstruct_unresolved(
        sub.store, sub.recovery_checkpoint_stream, sub.failed_positions_stream
    )
    return unresolved


# ──────────────────────────────────────────────────────────────────────
# Replay
# ──────────────────────────────────────────────────────────────────────


class TestReplayExhausted:
    def test_replay_reinvokes_handler_once_and_resolves(self, test_domain):
        sub = _subscription(test_domain)
        msg = _make_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)
        _drive_to_exhaustion(sub, msg)
        assert _latest_status(sub, 1) == FailedPositionStatus.EXHAUSTED.value

        record = _exhausted_record(sub, 1)
        # The operator has fixed the fault; the handler now succeeds.
        ToggleHandler.should_fail = False
        ToggleHandler.calls = 0

        resolved = asyncio.run(
            sub.replay_exhausted(
                msg,
                1,
                message_type=msg.metadata.headers.type,
                message_id=msg.metadata.headers.id,
                stream_name=record.data.get("stream_name"),
                stream_position=record.data.get("stream_position"),
                retry_count=record.data.get("retry_count", 0),
            )
        )

        assert resolved is True
        assert ToggleHandler.calls == 1
        assert _latest_status(sub, 1) == FailedPositionStatus.RESOLVED.value
        # A resolved position is not tracked on restart.
        assert 1 not in _rebuild(sub)

    def test_replay_that_fails_again_reopens_and_survives_rebuild(self, test_domain):
        sub = _subscription(test_domain)
        msg = _make_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)
        _drive_to_exhaustion(sub, msg)

        # Negative control: after exhaustion, a rebuild does NOT track the
        # position (Exhausted is terminal).
        assert 1 not in _rebuild(sub)

        record = _exhausted_record(sub, 1)
        # The fault is not fixed; replay fails again.
        ToggleHandler.calls = 0
        resolved = asyncio.run(
            sub.replay_exhausted(
                msg,
                1,
                message_type=msg.metadata.headers.type,
                message_id=msg.metadata.headers.id,
                stream_name=record.data.get("stream_name"),
                stream_position=record.data.get("stream_position"),
                retry_count=record.data.get("retry_count", 0),
            )
        )

        assert resolved is False
        assert ToggleHandler.calls == 1
        assert _latest_status(sub, 1) == FailedPositionStatus.FAILED.value

        # The reopen survives a rebuild: the position is tracked again, with a
        # fresh retry budget (count reset to 0).
        unresolved = _rebuild(sub)
        assert 1 in unresolved
        assert unresolved[1]["retry_count"] == 0

    def test_replay_does_not_move_the_read_cursor(self, test_domain):
        sub = _subscription(test_domain)
        msg = _make_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)
        _drive_to_exhaustion(sub, msg)
        record = _exhausted_record(sub, 1)

        sub.current_position = 5  # a cursor well past the failure
        ToggleHandler.should_fail = False

        asyncio.run(
            sub.replay_exhausted(
                msg,
                1,
                message_type=msg.metadata.headers.type,
                message_id=msg.metadata.headers.id,
                stream_name=record.data.get("stream_name"),
                stream_position=record.data.get("stream_position"),
                retry_count=record.data.get("retry_count", 0),
            )
        )

        assert sub.current_position == 5


# ──────────────────────────────────────────────────────────────────────
# Purge
# ──────────────────────────────────────────────────────────────────────


class TestPurgeExhausted:
    @staticmethod
    def _purge(sub: EventStoreSubscription, position: int, record: Message) -> None:
        """Append a Purged marker the way ``protean eventstore dlq purge`` does."""
        write_recovery_status_record(
            sub.store,
            sub.failed_positions_stream,
            sub.stream_category,
            sub.engine.domain.clock.now().isoformat(),
            position,
            FailedPositionStatus.PURGED,
            retry_count=record.data.get("retry_count", 0),
            message_type=record.data.get("message_type", "unknown"),
            message_id=record.data.get("message_id", "unknown"),
            stream_name=record.data.get("stream_name"),
            stream_position=record.data.get("stream_position"),
        )

    def test_purge_appends_terminal_marker_and_survives_rebuild(self, test_domain):
        sub = _subscription(test_domain)
        msg = _make_message(global_position=1, stream_position=0)
        _write_event_to_store(test_domain, msg)
        _drive_to_exhaustion(sub, msg)
        record = _exhausted_record(sub, 1)

        records_before = len(list(sub.store.read_all(sub.failed_positions_stream)))
        ToggleHandler.calls = 0

        self._purge(sub, 1, record)

        # The marker is terminal and last-written.
        assert _latest_status(sub, 1) == FailedPositionStatus.PURGED.value
        # Purge does not re-run the handler.
        assert ToggleHandler.calls == 0
        # A purged position is not tracked on restart.
        assert 1 not in _rebuild(sub)
        # History is kept, not deleted: the Exhausted record is still present,
        # and the Purged record is appended (one more record than before).
        records_after = list(sub.store.read_all(sub.failed_positions_stream))
        assert len(records_after) == records_before + 1
        statuses = [
            m.metadata.headers.type for m in records_after if m.metadata.headers
        ]
        assert FailedPositionStatus.EXHAUSTED.value in statuses
        # The Purged record mirrors the fields of the Exhausted record it clears.
        purged = next(
            m
            for m in records_after
            if m.metadata.headers
            and m.metadata.headers.type == FailedPositionStatus.PURGED.value
        )
        assert purged.data["stream_name"] == record.data.get("stream_name")
        assert purged.data["stream_position"] == record.data.get("stream_position")
        assert purged.data["message_type"] == record.data.get("message_type")

    def test_purged_record_is_terminal_in_the_rebuild(self, test_domain):
        """A ``Purged`` record drops a tracked position on rebuild.

        Isolates the terminal-set behavior from the purge-after-exhaustion path
        (where the preceding ``Exhausted`` record already dropped the position):
        here the position is still tracked (a lone ``Failed`` record) when the
        ``Purged`` record is folded, so only ``Purged`` being terminal can drop
        it.
        """
        sub = _subscription(test_domain)

        async def write_failed() -> None:
            await sub._record_failed_position(
                1,
                "Test.Registered.v1",
                "evt-1",
                stream_name="test-1",
                stream_position=0,
            )

        asyncio.run(write_failed())
        write_recovery_status_record(
            sub.store,
            sub.failed_positions_stream,
            sub.stream_category,
            sub.engine.domain.clock.now().isoformat(),
            1,
            FailedPositionStatus.PURGED,
            retry_count=0,
            message_type="Test.Registered.v1",
            message_id="evt-1",
            stream_name="test-1",
            stream_position=0,
        )

        # Control: the Failed record alone would track the position; the Purged
        # record must remove it.
        assert 1 not in _rebuild(sub)


# ──────────────────────────────────────────────────────────────────────
# Command-dispatcher replay (guards the CommandDispatcher isinstance fix)
# ──────────────────────────────────────────────────────────────────────


class TestReplayCommandDispatcher:
    def test_replay_resolves_a_command_dispatcher_position(self, test_domain):
        """Replay of a command-handler position resolves once the fault is fixed.

        A command stream's handler is a ``CommandDispatcher`` instance, so this
        drives replay through ``handle_message`` with an instance rather than a
        class. It guards the engine's ``isinstance(handler_cls, type)`` guard: a
        bare ``issubclass`` on the dispatcher raised, was swallowed, and made a
        succeeded command replay report a failure.
        """
        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(ToggleCommandHandler, part_of=Order)
        test_domain.init(traverse=False)
        ToggleCommandHandler.should_fail = True
        ToggleCommandHandler.calls = 0

        info, failed_stream = next(
            p for p in collect_failed_streams(test_domain) if p[0].is_command_handler
        )
        category = info.stream_category
        dispatcher = CommandDispatcher(
            category,
            {PlaceOrder.__type__: ToggleCommandHandler},
            ToggleCommandHandler,
        )
        engine = Engine(domain=test_domain, test_mode=False)
        sub = EventStoreSubscription(
            engine,
            category,
            dispatcher,
            messages_per_tick=10,
            position_update_interval=1,
            max_retries=MAX_RETRIES,
            enable_recovery=True,
            recovery_interval_seconds=0,
            retry_delay_seconds=0,
        )
        assert sub.failed_positions_stream == failed_stream

        cmd_stream = f"{category}-{uuid4()}"
        command = PlaceOrder(total="10")
        message = Message.from_domain_object(command)
        metadata_dict = message.metadata.to_dict()
        metadata_dict["event_store"] = EventStoreMeta(position=0, global_position=1)
        metadata_dict["domain"]["asynchronous"] = True
        metadata_dict["headers"]["stream"] = cmd_stream
        message.metadata = Metadata(**metadata_dict)
        test_domain.event_store.store._write(
            cmd_stream,
            message.metadata.headers.type,
            message.data,
            metadata=message.metadata.to_dict(),
        )

        try:
            asyncio.run(_run_to_exhaustion(sub, message))
            assert _latest_status(sub, 1) == FailedPositionStatus.EXHAUSTED.value

            # The operator fixes the fault; replay should now resolve.
            ToggleCommandHandler.should_fail = False
            ToggleCommandHandler.calls = 0
            record = _exhausted_record(sub, 1)
            resolved = asyncio.run(
                sub.replay_exhausted(
                    message,
                    1,
                    message_type=message.metadata.headers.type,
                    message_id=message.metadata.headers.id,
                    stream_name=cmd_stream,
                    stream_position=0,
                    retry_count=record.data.get("retry_count", 0),
                )
            )
        finally:
            engine.loop.close()

        assert resolved is True
        assert ToggleCommandHandler.calls == 1
        assert _latest_status(sub, 1) == FailedPositionStatus.RESOLVED.value


async def _run_to_exhaustion(sub: EventStoreSubscription, message: Message) -> None:
    await sub.process_batch([message])
    for _ in range(MAX_RETRIES + 1):
        await sub.run_recovery_pass()
