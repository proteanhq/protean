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
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
    FailedPositionStatus,
)
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


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_toggle():
    ToggleEventHandler.should_fail = True


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ToggleEventHandler, part_of=User)
    test_domain.register(SecondFailingHandler, part_of=User)
    test_domain.init(traverse=False)


def _create_message(
    global_position: int = 1,
    stream_position: int = 0,
    stream_name: str | None = None,
    idempotency_key: str | None = None,
    deadline: datetime | None = None,
) -> Message:
    user_id = str(uuid4())
    stream_name = stream_name or f"test-{user_id}"
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
    if idempotency_key is not None:
        metadata_dict["headers"]["idempotency_key"] = idempotency_key
    if deadline is not None:
        metadata_dict["headers"]["deadline"] = deadline
    message.metadata = Metadata(**metadata_dict)
    return message


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

    The failing command event is re-readable via the record's stream location and
    carries ``idempotency_key`` (or none) and an optional ``deadline``, so the
    replay confirmation and the expired-command guard can be exercised.
    """

    @test_domain.aggregate
    class Order:
        total: str

    @test_domain.command(part_of=Order)
    class PlaceOrder:
        total: str

    @test_domain.command_handler(part_of=Order)
    class OrderCommandHandler:
        @handle(PlaceOrder)
        def place(self, command):
            pass

    test_domain.init(traverse=False)

    info, stream = next(
        p for p in collect_failed_streams(test_domain) if p[0].is_command_handler
    )
    category = info.stream_category
    cmd_stream = f"{category}-{uuid4()}"

    msg = _create_message(
        global_position=position,
        stream_position=0,
        stream_name=cmd_stream,
        idempotency_key=idempotency_key,
        deadline=deadline,
    )
    _write_event_to_store(test_domain, msg)
    test_domain.event_store.store._write(
        stream,
        FailedPositionStatus.EXHAUSTED.value,
        {
            "position": position,
            "message_type": "PlaceOrder",
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
        from protean.utils import fqn

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
    def test_construction_failure_does_not_crash_the_finally(self, test_domain):
        """A raising ``Engine()`` leaves nothing to close; the guard skips it.

        Confirms the loop-leak guard: the engine is built inside the try, so a
        failed construction still runs the finally without an AttributeError on a
        None engine.
        """
        from protean.cli.eventstore import _redrive_engine

        with (
            patch("protean.server.Engine", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            with _redrive_engine(test_domain):
                pass  # pragma: no cover - Engine() raises before the body runs
