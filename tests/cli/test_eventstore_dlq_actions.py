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


class Order(BaseAggregate):
    total = String()


class PlaceOrder(BaseCommand):
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


def _create_message(
    global_position: int = 1,
    stream_position: int = 0,
    stream_name: str | None = None,
) -> Message:
    user_id = str(uuid4())
    user = User(id=user_id, email="test@example.com", name="Test")
    user.raise_(Registered(id=user_id, email="test@example.com", name="Test"))

    return _stamp(
        Message.from_domain_object(user._events[-1]),
        global_position=global_position,
        stream_position=stream_position,
        stream_name=stream_name or f"test-{user_id}",
    )


def _create_command_message(
    global_position: int,
    stream_name: str,
    *,
    stream_position: int = 0,
    idempotency_key: str | None = None,
    deadline: datetime | None = None,
) -> Message:
    """Build a stored ``PlaceOrder`` command message, ready to be re-read."""
    return _stamp(
        Message.from_domain_object(PlaceOrder(total="10")),
        global_position=global_position,
        stream_position=stream_position,
        stream_name=stream_name,
        idempotency_key=idempotency_key,
        deadline=deadline,
    )


def _write_event_to_store(test_domain, msg: Message) -> None:
    test_domain.event_store.store._write(
        msg.metadata.headers.stream,
        msg.metadata.headers.type,
        msg.data,
        metadata=msg.metadata.to_dict(),
    )


def _drive_to_exhaustion(
    test_domain,
    handler_cls,
    *,
    global_position: int = 1,
    max_retries: int = 2,
) -> Message:
    """Record a failed position for ``handler_cls`` and run recovery until it exhausts."""
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

    msg = _create_message(global_position=global_position, stream_position=0)
    _write_event_to_store(test_domain, msg)

    async def drive() -> None:
        await sub.process_batch([msg])
        for _ in range(max_retries + 1):
            await sub.run_recovery_pass()

    try:
        asyncio.run(drive())
    finally:
        engine.loop.close()
    return msg


def _exhaust_command_position(
    test_domain,
    position: int,
    *,
    idempotency_key: str | None = None,
    deadline: datetime | None = None,
) -> None:
    """Register a command handler and write an exhausted command position.

    The stored message is a real ``PlaceOrder`` command, so a replay routes it
    through the engine's ``CommandDispatcher`` to ``ToggleCommandHandler``. It is
    re-readable via the record's stream location and carries ``idempotency_key``
    (or none) and an optional ``deadline``, so the replay confirmation and the
    expired-command guard can be exercised too.
    """
    test_domain.register(Order)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(ToggleCommandHandler, part_of=Order)
    test_domain.init(traverse=False)

    info, stream = next(
        p for p in collect_failed_streams(test_domain) if p[0].is_command_handler
    )
    category = info.stream_category
    cmd_stream = f"{category}-{uuid4()}"

    msg = _create_command_message(
        position,
        cmd_stream,
        idempotency_key=idempotency_key,
        deadline=deadline,
    )
    _write_event_to_store(test_domain, msg)
    test_domain.event_store.store._write(
        stream,
        FailedPositionStatus.EXHAUSTED.value,
        {
            "position": position,
            "message_type": PlaceOrder.__type__,
            "message_id": str(uuid4()),
            "retry_count": 3,
            "stream_name": cmd_stream,
            "stream_position": 0,
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
        _exhaust_command_position(test_domain, 7, idempotency_key="idem-123")

        # Abort before re-drive: only the confirmation classification is under test.
        result = _invoke(
            ["eventstore", "dlq", "replay", "7", "--domain", "x.py"],
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
        _exhaust_command_position(test_domain, 8, idempotency_key=None)

        result = _invoke(
            ["eventstore", "dlq", "replay", "8", "--domain", "x.py"],
            domain=test_domain,
            input="n\n",
        )

        assert "a command with no idempotency key" in result.output
        assert "Aborted" in result.output

    def test_replay_dispatches_a_command_through_its_handler(self, test_domain):
        # A command stream's subscription handler is a CommandDispatcher, so the
        # CLI has to route the stored PlaceOrder through it to reach the handler.
        _exhaust_command_position(test_domain, 11)

        result = _invoke(
            ["eventstore", "dlq", "replay", "11", "--domain", "x.py", "--yes"],
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
        _exhaust_command_position(test_domain, 12)
        ToggleCommandHandler.should_fail = True  # fault still unfixed

        result = _invoke(
            ["eventstore", "dlq", "replay", "12", "--domain", "x.py", "--yes"],
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
        _drive_to_exhaustion(test_domain, ToggleEventHandler, global_position=1)
        _drive_to_exhaustion(test_domain, SecondFailingHandler, global_position=1)

        result = _invoke(
            ["eventstore", "dlq", "replay", "1", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "multiple subscriptions" in result.output
        assert "Pass --handler" in result.output

    def test_replay_handler_disambiguates(self, test_domain):
        # Same ambiguous setup; --handler picks one and it resolves.
        _drive_to_exhaustion(test_domain, ToggleEventHandler, global_position=1)
        _drive_to_exhaustion(test_domain, SecondFailingHandler, global_position=1)
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
        _exhaust_command_position(test_domain, 9, deadline=past)

        result = _invoke(
            ["eventstore", "dlq", "replay", "9", "--domain", "x.py", "--yes"],
            domain=test_domain,
        )

        assert result.exit_code == EXIT_USAGE
        assert "deadline has passed" in result.output

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
