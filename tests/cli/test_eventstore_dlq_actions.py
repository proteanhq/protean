"""Tests for the event-store DLQ action commands (replay / purge).

Drives a registered handler to exhaustion so its ``failed-*`` stream holds a
genuine ``Exhausted`` record, then exercises ``protean eventstore dlq replay``
and ``protean eventstore dlq purge`` over it (Typer ``CliRunner``). ``load_domain``
is patched to return the already-driven domain so its in-memory event store is
the one the commands act on.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from protean import apply
from protean.cli import app
from protean.cli.result import EXIT_FAILURE, EXIT_USAGE
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
    FailedPositionStatus,
    write_recovery_status_record,
)
from protean.utils import fqn
from protean.utils.dlq import collect_failed_streams, failed_positions_stream
from protean.utils.eventing import EventStoreMeta, Message, MessageType, Metadata
from protean.utils.mixins import handle

runner = CliRunner()

WIDE = {"COLUMNS": "200"}  # keep rich from wrapping the confirmation line


# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------


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


class ToggleEventHandler(BaseEventHandler):
    """Fails while ``should_fail`` is set."""

    should_fail = True

    @handle(Registered)
    def handle_registered(self, event):
        if type(self).should_fail:
            raise RuntimeError("boom")


class SecondFailingHandler(BaseEventHandler):
    """Always fails; used only to create a second exhausted owner."""

    @handle(Registered)
    def handle_registered(self, event):
        raise RuntimeError("boom")


class UserListing(BaseProjection):
    id = Identifier(identifier=True)
    email = String()


class FailingProjector(BaseProjector):
    """Always fails; used to exhaust a position owned by a projector."""

    @handle(Registered)
    def project(self, event):
        raise RuntimeError("boom")


class Order(BaseAggregate):
    total = String()


class PlaceOrder(BaseCommand):
    total = String()


class CancelOrder(BaseCommand):
    """A command on the same category that no handler handles.

    Stands in for a handler that was removed or renamed while the category's
    other command handlers kept its ``CommandDispatcher`` alive.
    """

    total = String()


class ToggleCommandHandler(BaseCommandHandler):
    """Fails while ``should_fail`` is set; counts every invocation."""

    should_fail = False
    calls = 0

    @handle(PlaceOrder)
    def place(self, command):
        type(self).calls += 1
        if type(self).should_fail:
            raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_toggle():
    ToggleEventHandler.should_fail = True
    ToggleCommandHandler.should_fail = False
    ToggleCommandHandler.calls = 0


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ToggleEventHandler, part_of=User)
    test_domain.register(SecondFailingHandler, part_of=User)
    test_domain.init(traverse=False)


def _stamp(
    message: Message,
    *,
    global_position: int,
    stream_position: int,
    stream_name: str,
    idempotency_key: str | None = None,
    deadline: datetime | None = None,
) -> Message:
    """Place ``message`` at a stream location, with optional command headers."""
    metadata_dict = message.metadata.to_dict()
    metadata_dict["event_store"] = EventStoreMeta(
        position=stream_position, global_position=global_position
    )
    metadata_dict["domain"]["asynchronous"] = True
    headers = metadata_dict.get("headers") or {}
    headers["stream"] = stream_name
    if idempotency_key is not None:
        headers["idempotency_key"] = idempotency_key
    if deadline is not None:
        headers["deadline"] = deadline
    metadata_dict["headers"] = headers
    message.metadata = Metadata(**metadata_dict)
    return message


def _create_message(stream_name: str | None = None) -> Message:
    """Build an event message to write to the store.

    The stamped positions are placeholders — the store assigns the real ones on
    write.
    """
    user_id = str(uuid4())
    user = User(id=user_id, email="test@example.com", name="Test")
    user.raise_(Registered(id=user_id, email="test@example.com", name="Test"))

    return _stamp(
        Message.from_domain_object(user._events[-1]),
        global_position=0,
        stream_position=0,
        stream_name=stream_name or f"test-{user_id}",
    )


def _create_command_message(
    stream_name: str,
    *,
    idempotency_key: str | None = None,
    deadline: datetime | None = None,
    command_cls: type[BaseCommand] = PlaceOrder,
) -> Message:
    """Build a command message to write to the store.

    ``command_cls`` defaults to ``PlaceOrder``, the command the dispatcher routes
    to ``ToggleCommandHandler``; pass ``CancelOrder`` for one it cannot route.
    The stamped positions are placeholders — the store assigns the real ones on
    write.
    """
    return _stamp(
        Message.from_domain_object(command_cls(total="10")),
        global_position=0,
        stream_position=0,
        stream_name=stream_name,
        idempotency_key=idempotency_key,
        deadline=deadline,
    )


def _write_event_to_store(test_domain, msg: Message) -> Message:
    """Write ``msg`` to the store and return it as stored.

    The store assigns the positions, so the stored copy is what the rest of a
    test has to work from: a record built off the in-memory message would name a
    global position no message sits at.
    """
    store = test_domain.event_store.store
    stream = msg.metadata.headers.stream
    store._write(
        stream, msg.metadata.headers.type, msg.data, metadata=msg.metadata.to_dict()
    )
    return store.read(stream, position=0, no_of_messages=1)[0]


def _drive_to_exhaustion(
    test_domain,
    handler_cls,
    *,
    message: Message | None = None,
    max_retries: int = 2,
) -> Message:
    """Record a failed position for ``handler_cls`` and run recovery until it exhausts.

    Writes and drives a fresh event unless ``message`` names one already stored.
    Pass a returned message back in to exhaust the same event under a second
    handler, the way two handlers on one stream share a global position.
    """
    category = User.meta_.stream_category
    engine = Engine(domain=test_domain, test_mode=False)
    sub = EventStoreSubscription(
        engine,
        category,
        handler_cls,
        messages_per_tick=10,
        position_update_interval=1,
        max_retries=max_retries,
        enable_recovery=True,
        recovery_interval_seconds=0,
        retry_delay_seconds=0,
    )

    if message is None:
        message = _write_event_to_store(test_domain, _create_message())

    async def drive() -> None:
        await sub.process_batch([message])
        for _ in range(max_retries + 1):
            await sub.run_recovery_pass()

    try:
        asyncio.run(drive())
    finally:
        engine.loop.close()
    return message


def _exhaust_command_position(
    test_domain,
    *,
    idempotency_key: str | None = None,
    deadline: datetime | None = None,
    command_cls: type[BaseCommand] = PlaceOrder,
) -> int:
    """Register a command handler and write an exhausted command position.

    The stored message is a real ``PlaceOrder`` command, so a replay routes it
    through the engine's ``CommandDispatcher`` to ``ToggleCommandHandler``. It is
    re-readable via the record's stream location and carries ``idempotency_key``
    (or none) and an optional ``deadline``, so the replay confirmation and the
    expired-command guard can be exercised too.

    Pass ``command_cls=CancelOrder`` to exhaust a command the dispatcher has no
    handler for; ``PlaceOrder``'s handler still keeps the dispatcher alive.

    Returns the global position the store placed the command at, which is the
    position the ``Exhausted`` record names.
    """
    test_domain.register(Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(CancelOrder, part_of=Order)
    test_domain.register(ToggleCommandHandler, part_of=Order)
    test_domain.init(traverse=False)

    info, stream = next(
        p for p in collect_failed_streams(test_domain) if p[0].is_command_handler
    )
    category = info.stream_category
    cmd_stream = f"{category}-{uuid4()}"

    stored = _write_event_to_store(
        test_domain,
        _create_command_message(
            cmd_stream,
            idempotency_key=idempotency_key,
            deadline=deadline,
            command_cls=command_cls,
        ),
    )
    position = stored.metadata.event_store.global_position
    test_domain.event_store.store._write(
        stream,
        FailedPositionStatus.EXHAUSTED.value,
        {
            "position": position,
            "message_type": stored.metadata.headers.type,
            "message_id": str(uuid4()),
            "retry_count": 3,
            "stream_name": cmd_stream,
            "stream_position": stored.metadata.event_store.position,
        },
        metadata={
            "headers": {
                "type": FailedPositionStatus.EXHAUSTED.value,
                "stream": stream,
            },
            "domain": {
                "kind": MessageType.READ_POSITION.value,
                "origin_stream": category,
            },
        },
    )
    return position


def _exhaust_projector_position(test_domain) -> int:
    """Register a projector and drive one position to exhaustion under it.

    Projectors are event-store subscriptions too, so the DLQ commands can land on
    one. Registering it only here keeps the other tests' owner lookups unchanged.
    Returns the exhausted global position.
    """
    test_domain.register(UserListing)
    test_domain.register(FailingProjector, projector_for=UserListing, aggregates=[User])
    test_domain.init(traverse=False)

    msg = _drive_to_exhaustion(test_domain, FailingProjector)
    return msg.metadata.event_store.global_position


def _toggle_failed_stream(test_domain) -> tuple:
    """Return (subscription info, failed stream) for ``ToggleEventHandler``."""
    return next(
        p
        for p in collect_failed_streams(test_domain)
        if p[0].handler_name == "ToggleEventHandler"
    )


def _resolve_concurrently(test_domain, position: int = 1) -> None:
    """Append a Resolved record, the way another operator's replay would.

    Used from inside a patched confirmation prompt to reproduce the race: the
    position is cleared between the owner lookup and the action.
    """
    info, stream = _toggle_failed_stream(test_domain)
    write_recovery_status_record(
        test_domain.event_store.store,
        stream,
        info.stream_category,
        test_domain.clock.now().isoformat(),
        position,
        FailedPositionStatus.RESOLVED,
        retry_count=3,
    )


def _invoke(args, **kwargs):
    with patch("protean.cli.eventstore.load_domain", return_value=kwargs.pop("domain")):
        return runner.invoke(app, args, env=WIDE, **kwargs)


# ---------------------------------------------------------------------------
# protean eventstore dlq replay
# ---------------------------------------------------------------------------


class TestReplay:
    def test_replay_reopens_when_handler_fails_again(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)  # still failing

        result = _invoke(
            ["eventstore", "dlq", "replay", "1", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        # A reopen exits non-zero so a script can tell it from a resolution.
        assert result.exit_code == EXIT_FAILURE
        assert "event handler" in result.output
        assert "reopened" in result.output

    def test_replay_resolves_after_the_fault_is_fixed(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)
        ToggleEventHandler.should_fail = False  # operator fixed the fault

        result = _invoke(
            ["eventstore", "dlq", "replay", "1", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == 0, result.output
        assert "resolved" in result.output

        # The position is no longer exhausted.
        listing = _invoke(
            ["eventstore", "dlq", "list", "--domain", "x.py"], domain=test_domain
        )
        assert "No exhausted positions." in listing.output

    def test_replay_aborts_on_no(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)

        result = _invoke(
            ["eventstore", "dlq", "replay", "1", "--domain", "x.py"],
            domain=test_domain,
            input="n\n",
        )

        assert result.exit_code != 0  # Typer aborts
        assert "Aborted" in result.output
        # The position is still exhausted (nothing was re-driven).
        listing = _invoke(
            ["eventstore", "dlq", "list", "--domain", "x.py", "--json"],
            domain=test_domain,
        )
        assert '"exhausted": [' in listing.output

    def test_replay_names_the_idempotency_key_case(self, test_domain):
        position = _exhaust_command_position(test_domain, idempotency_key="idem-123")

        # Abort before re-drive: only the confirmation classification is under test.
        result = _invoke(
            ["eventstore", "dlq", "replay", str(position), "--domain", "x.py"],
            domain=test_domain,
            input="n\n",
        )

        # Replay bypasses the idempotency store, so the prompt names the key but
        # does not claim the re-run is deduplicated.
        assert "a command with an idempotency key" in result.output
        assert "side effects apply again" in result.output
        assert "deduplicated" not in result.output
        assert "Aborted" in result.output

    def test_replay_names_double_apply_for_command_without_idempotency_key(
        self, test_domain
    ):
        position = _exhaust_command_position(test_domain, idempotency_key=None)

        result = _invoke(
            ["eventstore", "dlq", "replay", str(position), "--domain", "x.py"],
            domain=test_domain,
            input="n\n",
        )

        assert "a command with no idempotency key" in result.output
        assert "Aborted" in result.output

    def test_replay_names_a_projector_target(self, test_domain):
        # A projector owns its failed stream directly, and replaying its position
        # re-applies the projection writes, so the prompt must not call it an
        # event handler.
        position = _exhaust_projector_position(test_domain)

        result = _invoke(
            ["eventstore", "dlq", "replay", str(position), "--domain", "x.py"],
            domain=test_domain,
            input="n\n",
        )

        assert "targets a projector" in result.output
        assert "projection writes a second time" in result.output
        assert "event handler" not in result.output
        assert "Aborted" in result.output

    def test_replay_dispatches_a_command_through_its_handler(self, test_domain):
        # A command stream's subscription handler is a CommandDispatcher, so the
        # CLI has to route the stored PlaceOrder through it to reach the handler.
        position = _exhaust_command_position(test_domain)

        result = _invoke(
            ["eventstore", "dlq", "replay", str(position), "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == 0, result.output
        assert "resolved" in result.output
        assert ToggleCommandHandler.calls == 1

        listing = _invoke(
            ["eventstore", "dlq", "list", "--domain", "x.py"], domain=test_domain
        )
        assert "No exhausted positions." in listing.output

    def test_replay_reopens_a_command_whose_handler_fails_again(self, test_domain):
        position = _exhaust_command_position(test_domain)
        ToggleCommandHandler.should_fail = True  # fault still unfixed

        result = _invoke(
            ["eventstore", "dlq", "replay", str(position), "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_FAILURE
        assert "reopened" in result.output
        assert ToggleCommandHandler.calls == 1

    def test_replay_refuses_a_position_cleared_while_the_prompt_was_open(
        self, test_domain
    ):
        # Another operator resolves the position while this command waits on the
        # prompt. Replay must re-check and refuse, or it would dispatch the
        # handler a second time.
        _drive_to_exhaustion(test_domain, ToggleEventHandler)
        ToggleEventHandler.should_fail = False  # a dispatch would succeed
        store = test_domain.event_store.store
        _info, stream = _toggle_failed_stream(test_domain)
        records_at_confirm = {}

        def _resolve_at_the_prompt(*args, **kwargs):
            _resolve_concurrently(test_domain)
            records_at_confirm["count"] = len(list(store.read_all(stream)))
            return True

        with patch("typer.confirm", side_effect=_resolve_at_the_prompt):
            result = _invoke(
                ["eventstore", "dlq", "replay", "1", "--domain", "x.py"],
                domain=test_domain,
            )

        assert result.exit_code == EXIT_USAGE
        assert "no longer exhausted" in result.output
        # Nothing was dispatched, so nothing was recorded either.
        assert len(list(store.read_all(stream))) == records_at_confirm["count"]

    def test_replay_unknown_position_is_usage_error(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)

        result = _invoke(
            ["eventstore", "dlq", "replay", "999", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "No exhausted position 999 found" in result.output

    def test_replay_unknown_subscription_is_usage_error(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)

        result = _invoke(
            [
                "eventstore",
                "dlq",
                "replay",
                "1",
                "--domain",
                "x.py",
                "--subscription",
                "nope",
                "--yes",
            ],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "No event-store subscription found" in result.output

    def test_replay_ambiguous_owners_asks_for_handler(self, test_domain):
        # Two handlers on the same stream (same category) both exhaust position 1.
        # --subscription can't separate them, so the error asks for --handler.
        msg = _drive_to_exhaustion(test_domain, ToggleEventHandler)
        _drive_to_exhaustion(test_domain, SecondFailingHandler, message=msg)

        result = _invoke(
            ["eventstore", "dlq", "replay", "1", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "multiple subscriptions" in result.output
        assert "Pass --handler" in result.output

    def test_replay_handler_disambiguates(self, test_domain):
        # Same ambiguous setup; --handler picks one and it resolves.
        msg = _drive_to_exhaustion(test_domain, ToggleEventHandler)
        _drive_to_exhaustion(test_domain, SecondFailingHandler, message=msg)
        ToggleEventHandler.should_fail = False

        result = _invoke(
            [
                "eventstore",
                "dlq",
                "replay",
                "1",
                "--domain",
                "x.py",
                "--handler",
                "ToggleEventHandler",
                "--yes",
            ],
            domain=test_domain,
        )

        assert result.exit_code == 0, result.output
        assert "resolved" in result.output

    def test_replay_unknown_handler_is_usage_error(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)

        result = _invoke(
            [
                "eventstore",
                "dlq",
                "replay",
                "1",
                "--domain",
                "x.py",
                "--handler",
                "NoSuchHandler",
                "--yes",
            ],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "No event-store subscription found for handler" in result.output

    def test_replay_refuses_an_expired_command(self, test_domain):
        # A command whose deadline passed would be skipped, not run, so replay
        # must refuse rather than falsely resolve it.
        past = datetime(2020, 1, 1, tzinfo=UTC)
        position = _exhaust_command_position(test_domain, deadline=past)

        result = _invoke(
            ["eventstore", "dlq", "replay", str(position), "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "deadline has passed" in result.output

    def test_replay_refuses_a_command_with_no_registered_handler(self, test_domain):
        # The command's handler was removed or renamed, but PlaceOrder's handler
        # keeps the category's dispatcher alive. The dispatcher finds nothing to
        # route CancelOrder to and only logs, and the engine still reports the
        # message handled, so replay would write a Resolved record with no
        # handler having run.
        position = _exhaust_command_position(test_domain, command_cls=CancelOrder)

        result = _invoke(
            ["eventstore", "dlq", "replay", str(position), "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert f"no handler for the message at position {position}" in result.output
        # Nothing ran and the position is still there to purge or fix.
        assert ToggleCommandHandler.calls == 0
        listing = _invoke(
            ["eventstore", "dlq", "list", "--domain", "x.py", "--json"],
            domain=test_domain,
        )
        assert str(position) in listing.output

    def test_replay_refuses_when_the_re_read_lands_on_another_message(
        self, test_domain
    ):
        # Store reads are inclusive, so a re-read of a position whose own message
        # is gone (a partial restore, a global-position gap) comes back with the
        # next message in the stream. Replay must refuse it: dispatching it would
        # run a handler on an unrelated event and resolve the requested position.
        store = test_domain.event_store.store
        category = User.meta_.stream_category
        msg = _create_message(stream_name=f"{category}-{uuid4()}")
        _write_event_to_store(test_domain, msg)
        stored_at = store.read(category, position=0, no_of_messages=1)[
            0
        ].metadata.event_store.global_position

        # A pre-enrichment record (no stream location) at a global position the
        # category holds no message at; the read lands on ``stored_at`` instead.
        failed_stream = failed_positions_stream(fqn(ToggleEventHandler), category)
        missing = stored_at - 1
        store._write(
            failed_stream,
            FailedPositionStatus.EXHAUSTED.value,
            {
                "position": missing,
                "message_type": "Test.Registered.v1",
                "message_id": "evt-gone",
                "retry_count": 3,
            },
            metadata={
                "headers": {
                    "id": "rec-gone",
                    "type": FailedPositionStatus.EXHAUSTED.value,
                    "stream": failed_stream,
                },
                "domain": {
                    "kind": MessageType.READ_POSITION.value,
                    "origin_stream": category,
                },
            },
        )
        ToggleEventHandler.should_fail = False  # a dispatch would resolve it

        result = _invoke(
            ["eventstore", "dlq", "replay", str(missing), "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "Could not re-read the event" in result.output
        # The position is untouched, so it can still be purged.
        listing = _invoke(
            ["eventstore", "dlq", "list", "--domain", "x.py", "--json"],
            domain=test_domain,
        )
        assert str(missing) in listing.output

    def test_replay_refuses_a_refill_that_reused_the_stream_ordinal(self, test_domain):
        # A restore dropped a stream's tail and a later append refilled the same
        # per-stream ordinal. The re-read lands on the refill, whose ordinal
        # matches the record's but whose global position does not. Replay must
        # refuse: the refill is a different event.
        store = test_domain.event_store.store
        category = User.meta_.stream_category
        _write_event_to_store(test_domain, _create_message())  # holds global 1
        stream = f"{category}-{uuid4()}"
        refill = _write_event_to_store(test_domain, _create_message(stream_name=stream))
        stored_at = refill.metadata.event_store.global_position

        gone = stored_at - 1  # the global position the dropped event held
        failed_stream = failed_positions_stream(fqn(ToggleEventHandler), category)
        store._write(
            failed_stream,
            FailedPositionStatus.EXHAUSTED.value,
            {
                "position": gone,
                "message_type": "Test.Registered.v1",
                "message_id": "evt-dropped",
                "retry_count": 3,
                "stream_name": stream,
                "stream_position": refill.metadata.event_store.position,
            },
            metadata={
                "headers": {
                    "id": "rec-dropped",
                    "type": FailedPositionStatus.EXHAUSTED.value,
                    "stream": failed_stream,
                },
                "domain": {
                    "kind": MessageType.READ_POSITION.value,
                    "origin_stream": category,
                },
            },
        )
        ToggleEventHandler.should_fail = False  # a dispatch would resolve it

        result = _invoke(
            ["eventstore", "dlq", "replay", str(gone), "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "Could not re-read the event" in result.output
        # The position is untouched, so it can still be purged.
        listing = _invoke(
            ["eventstore", "dlq", "list", "--domain", "x.py", "--json"],
            domain=test_domain,
        )
        assert str(gone) in listing.output

    def test_replay_unreadable_event_is_usage_error(self, test_domain):
        # An Exhausted record with no stream location and no origin stream.
        store = test_domain.event_store.store
        category = User.meta_.stream_category
        failed_stream = failed_positions_stream(fqn(ToggleEventHandler), category)
        store._write(
            failed_stream,
            FailedPositionStatus.EXHAUSTED.value,
            {
                "position": 7,
                "message_type": "Test.Registered.v1",
                "message_id": "evt-x",
                "retry_count": 3,
                "stream_name": None,
                "stream_position": None,
            },
            metadata={
                "headers": {
                    "id": "rec-x",
                    "type": FailedPositionStatus.EXHAUSTED.value,
                    "stream": failed_stream,
                },
                "domain": {"kind": "read_position"},  # no origin_stream
            },
        )

        result = _invoke(
            ["eventstore", "dlq", "replay", "7", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "Could not re-read the event" in result.output


# ---------------------------------------------------------------------------
# protean eventstore dlq purge
# ---------------------------------------------------------------------------


class TestPurge:
    def test_purge_delists_the_position(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)

        result = _invoke(
            ["eventstore", "dlq", "purge", "1", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == 0, result.output
        assert "Purged position 1" in result.output

        listing = _invoke(
            ["eventstore", "dlq", "list", "--domain", "x.py"], domain=test_domain
        )
        assert "No exhausted positions." in listing.output

    def test_purge_refuses_a_position_cleared_while_the_prompt_was_open(
        self, test_domain
    ):
        # Another operator resolves the position while this command waits on the
        # prompt. Purge must re-check and refuse, or it would mark a position
        # that is no longer exhausted.
        _drive_to_exhaustion(test_domain, ToggleEventHandler)
        store = test_domain.event_store.store
        _info, stream = _toggle_failed_stream(test_domain)
        records_at_confirm = {}

        def _resolve_at_the_prompt(*args, **kwargs):
            _resolve_concurrently(test_domain)
            records_at_confirm["count"] = len(list(store.read_all(stream)))
            return True

        with patch("typer.confirm", side_effect=_resolve_at_the_prompt):
            result = _invoke(
                ["eventstore", "dlq", "purge", "1", "--domain", "x.py"],
                domain=test_domain,
            )

        assert result.exit_code == EXIT_USAGE
        assert "no longer exhausted" in result.output
        # No Purged marker was appended.
        assert len(list(store.read_all(stream))) == records_at_confirm["count"]

    def test_purged_position_cannot_be_acted_on_again(self, test_domain):
        # After a purge, the latest status is Purged, so replay/purge must not
        # find the position through the stale Exhausted record.
        _drive_to_exhaustion(test_domain, ToggleEventHandler)
        purged = _invoke(
            ["eventstore", "dlq", "purge", "1", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )
        assert purged.exit_code == 0, purged.output

        for verb in ("replay", "purge"):
            again = _invoke(
                ["eventstore", "dlq", verb, "1", "--domain", "x.py", "--yes"],
                domain=test_domain,
            )
            assert again.exit_code == EXIT_USAGE, (verb, again.output)
            assert "No exhausted position 1 found" in again.output

    def test_purge_aborts_on_no(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)

        result = _invoke(
            ["eventstore", "dlq", "purge", "1", "--domain", "x.py"],
            domain=test_domain,
            input="n\n",
        )

        assert result.exit_code != 0
        assert "Aborted" in result.output
        # Still exhausted.
        listing = _invoke(
            ["eventstore", "dlq", "list", "--domain", "x.py", "--json"],
            domain=test_domain,
        )
        assert '"exhausted": [' in listing.output

    def test_purge_unknown_position_is_usage_error(self, test_domain):
        _drive_to_exhaustion(test_domain, ToggleEventHandler)

        result = _invoke(
            ["eventstore", "dlq", "purge", "999", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "No exhausted position 999 found" in result.output


# ---------------------------------------------------------------------------
# Owner-subscription lookup
# ---------------------------------------------------------------------------


class TestOwnerSubscription:
    def test_returns_none_when_no_subscription_owns_the_stream(self, test_domain):
        from protean.cli.eventstore import _owner_subscription

        engine = Engine(domain=test_domain, test_mode=True)
        try:
            assert _owner_subscription(engine, "failed-nobody-owns-this") is None
        finally:
            engine.loop.close()


class TestRedriveEngine:
    def test_closes_the_engine_loop_on_the_way_out(self, test_domain):
        """The loop the engine opens is closed once the body is done."""
        from protean.cli.eventstore import _redrive_engine

        with _redrive_engine(test_domain) as engine:
            assert engine.loop.is_closed() is False

        assert engine.loop.is_closed() is True

    def test_construction_failure_propagates(self, test_domain):
        """A raising ``Engine()`` raises through, with no loop left to close.

        A half-built engine closes its own loop in ``Engine.__init__``, so the
        context manager has nothing to clean up (see
        ``tests/server/test_engine_initialization.py``).
        """
        from protean.cli.eventstore import _redrive_engine

        with (
            patch("protean.server.Engine", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            with _redrive_engine(test_domain):
                pass  # pragma: no cover - Engine() raises before the body runs
