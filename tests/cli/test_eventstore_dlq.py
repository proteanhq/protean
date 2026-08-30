"""Tests for CLI event-store DLQ commands (protean eventstore dlq ...).

Drives a real registered domain to exhaustion (process a message, then run the
recovery pass past ``max_retries``) so the ``failed-*`` stream holds a genuine
``Exhausted`` record, then exercises ``list`` and ``inspect`` over it. The CLI's
``load_domain`` is patched to return this already-driven domain so its in-memory
event store (holding the exhausted records) is the one the commands read.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch
from uuid import uuid4

from typer.testing import CliRunner

from protean import apply
from protean.cli import app
from protean.cli.result import EXIT_USAGE
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
    FailedPositionStatus,
)
from protean.utils.dlq import collect_failed_streams, command_dispatcher_fqn
from protean.utils.eventing import EventStoreMeta, Message, MessageType, Metadata
from protean.utils.mixins import handle
from tests.cli._envelope import assert_envelope

runner = CliRunner()


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


class AlwaysFailingEventHandler(BaseEventHandler):
    """Handler that always raises, so its position exhausts."""

    @handle(Registered)
    def handle_registered(self, event):
        raise RuntimeError("Permanent failure")


class NotifySubscriber(BaseSubscriber):
    """A broker subscriber — it has no event-store failed stream."""

    def __call__(self, payload: dict) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_message(global_position: int, stream_position: int, stream_name: str):
    """Build a Registered event message pinned to a known stream location."""
    user_id = str(uuid4())
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


def _register(test_domain) -> None:
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(AlwaysFailingEventHandler, part_of=User)
    test_domain.init(traverse=False)


def _drive_to_exhaustion(
    test_domain,
    *,
    max_retries: int = 2,
    stream_name: str | None = None,
) -> Message:
    """Record a failed position and run recovery until it exhausts.

    Uses the aggregate's inferred stream category so the failed-positions stream
    the subscription writes to is exactly the one the CLI derives.
    """
    stream_name = stream_name or f"test-{uuid4()}"
    category = User.meta_.stream_category
    engine = Engine(domain=test_domain, test_mode=False)
    sub = EventStoreSubscription(
        engine,
        category,
        AlwaysFailingEventHandler,
        messages_per_tick=10,
        position_update_interval=1,
        max_retries=max_retries,
        enable_recovery=True,
        recovery_interval_seconds=0,
        retry_delay_seconds=0,
    )

    msg = _create_message(global_position=1, stream_position=0, stream_name=stream_name)
    _write_event_to_store(test_domain, msg)

    async def drive() -> None:
        await sub.process_batch([msg])
        # One extra pass beyond max_retries takes the position terminal.
        for _ in range(max_retries + 1):
            await sub.run_recovery_pass()

    try:
        asyncio.run(drive())
    finally:
        # Engine() opens its own event loop that asyncio.run never uses; close
        # it so the suite does not leak loops across tests.
        engine.loop.close()
    return msg


def _record_failed_only(test_domain, *, stream_name: str | None = None) -> None:
    """Record a failed position and retry once, but never exhaust it."""
    stream_name = stream_name or f"test-{uuid4()}"
    category = User.meta_.stream_category
    engine = Engine(domain=test_domain, test_mode=False)
    sub = EventStoreSubscription(
        engine,
        category,
        AlwaysFailingEventHandler,
        messages_per_tick=10,
        position_update_interval=1,
        max_retries=100,  # high, so a single retry leaves it FAILED, not exhausted
        enable_recovery=True,
        recovery_interval_seconds=0,
        retry_delay_seconds=0,
    )

    msg = _create_message(global_position=1, stream_position=0, stream_name=stream_name)
    _write_event_to_store(test_domain, msg)

    async def drive() -> None:
        await sub.process_batch([msg])
        await sub.run_recovery_pass()

    try:
        asyncio.run(drive())
    finally:
        engine.loop.close()


# ---------------------------------------------------------------------------
# protean eventstore dlq list
# ---------------------------------------------------------------------------


class TestEventstoreDlqList:
    def test_lists_exhausted_position(self, test_domain):
        _register(test_domain)
        _drive_to_exhaustion(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            # Widen the terminal so rich does not wrap the long handler FQN.
            result = runner.invoke(
                app,
                ["eventstore", "dlq", "list", "--domain", "x.py"],
                env={"COLUMNS": "200"},
            )

        assert result.exit_code == 0, result.output
        assert "AlwaysFailingEventHandler" in result.output
        assert User.meta_.stream_category in result.output
        assert "1 exhausted position(s)" in result.output

    def test_empty_when_no_exhausted_positions(self, test_domain):
        _register(test_domain)
        _record_failed_only(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "list", "--domain", "x.py"]
            )

        assert result.exit_code == 0, result.output
        assert "No exhausted positions." in result.output

    def test_only_failed_position_is_not_listed(self, test_domain):
        """A position whose latest record is FAILED (never exhausted) is excluded."""
        _register(test_domain)
        _record_failed_only(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "list", "--domain", "x.py", "--json"]
            )

        assert result.exit_code == 0, result.output
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        assert env["data"]["subscriptions"] == []

    def test_json_lists_exhausted_position(self, test_domain):
        _register(test_domain)
        _drive_to_exhaustion(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "list", "--domain", "x.py", "--json"]
            )

        assert result.exit_code == 0, result.output
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        subs = env["data"]["subscriptions"]
        assert len(subs) == 1
        assert subs[0]["stream_category"] == User.meta_.stream_category
        assert subs[0]["exhausted"] == [1]

    def test_broker_subscriber_is_excluded(self, test_domain):
        """A broker subscriber has no event-store failed stream, so it never
        appears in the exhausted-position listing."""
        _register(test_domain)
        test_domain.register(NotifySubscriber, stream="person_added")
        test_domain.init(traverse=False)
        _drive_to_exhaustion(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "list", "--domain", "x.py", "--json"]
            )

        assert result.exit_code == 0, result.output
        env = assert_envelope(result.stdout)
        categories = [s["stream_category"] for s in env["data"]["subscriptions"]]
        assert "person_added" not in categories
        assert User.meta_.stream_category in categories

    def test_command_handler_reports_dispatcher_identity(self, test_domain):
        """A command handler's exhausted positions report the dispatcher fqn.

        The engine fans a command stream's handlers into one CommandDispatcher
        subscription and writes the exhausted records under the dispatcher's
        stream, so ``list`` must name that dispatcher, not the concrete handler
        class (which would misidentify the writer and hide sibling handlers).
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

        # A command handler's stream is the command stream (``...:command``), and
        # the engine writes its exhausted records under the CommandDispatcher, so
        # locate the exact failed stream through discovery rather than guessing.
        info, stream = next(
            p for p in collect_failed_streams(test_domain) if p[0].is_command_handler
        )
        category = info.stream_category
        test_domain.event_store.store._write(
            stream,
            FailedPositionStatus.EXHAUSTED.value,
            {
                "position": 7,
                "message_type": "PlaceOrder",
                "message_id": str(uuid4()),
                "retry_count": 3,
                "stream_name": f"{category}-{uuid4()}",
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

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "list", "--domain", "x.py", "--json"]
            )

        assert result.exit_code == 0, result.output
        env = assert_envelope(result.stdout)
        sub = next(
            s for s in env["data"]["subscriptions"] if s["stream_category"] == category
        )
        assert sub["handler"] == command_dispatcher_fqn(category)
        assert sub["exhausted"] == [7]

    def test_unknown_subscription_is_usage_error(self, test_domain):
        _register(test_domain)
        _drive_to_exhaustion(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app,
                [
                    "eventstore",
                    "dlq",
                    "list",
                    "--domain",
                    "x.py",
                    "--subscription",
                    "nope",
                ],
            )

        assert result.exit_code == EXIT_USAGE
        assert "No event-store subscription found" in result.output


# ---------------------------------------------------------------------------
# protean eventstore dlq inspect
# ---------------------------------------------------------------------------


class TestEventstoreDlqInspect:
    def test_inspect_reads_failing_event(self, test_domain):
        _register(test_domain)
        _drive_to_exhaustion(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "inspect", "1", "--domain", "x.py"]
            )

        assert result.exit_code == 0, result.output
        assert "Registered" in result.output
        assert "test@example.com" in result.output

    def test_inspect_json_has_four_keys(self, test_domain):
        _register(test_domain)
        _drive_to_exhaustion(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "inspect", "1", "--domain", "x.py", "--json"]
            )

        assert result.exit_code == 0, result.output
        env = assert_envelope(result.stdout)
        assert env["status"] == "pass"
        data = env["data"]
        assert data["position"] == 1
        assert "Registered" in data["type"]
        assert data["global_position"] is not None
        assert data["data"]["email"] == "test@example.com"

    def test_inspect_falls_back_to_origin_stream_for_old_records(self, test_domain):
        """A pre-enrichment Exhausted record (no stream_name/stream_position)
        falls back to the origin category stream, read by global position."""
        from protean.server.subscription.event_store_subscription import (
            FailedPositionStatus,
        )
        from protean.utils import fqn
        from protean.utils.dlq import failed_positions_stream

        _register(test_domain)
        store = test_domain.event_store.store
        category = User.meta_.stream_category  # "test::user"

        # The failing event lives in a stream under the origin category, so a
        # category read by global position can find it.
        store._write(
            f"{category}-abc",
            "Test.Registered.v1",
            {"id": "abc", "email": "old@example.com", "name": "Old"},
            metadata={
                "headers": {
                    "id": "evt-1",
                    "type": "Test.Registered.v1",
                    "stream": f"{category}-abc",
                },
                "domain": {"kind": "EVENT"},
            },
        )
        global_position = store.read(category, position=1, no_of_messages=1)[
            0
        ].metadata.event_store.global_position

        # A pre-enrichment Exhausted record: no stream_name/stream_position,
        # only the origin stream on the metadata.
        failed_stream = failed_positions_stream(
            fqn(AlwaysFailingEventHandler), category
        )
        store._write(
            failed_stream,
            FailedPositionStatus.EXHAUSTED.value,
            {
                "position": global_position,
                "message_type": "Test.Registered.v1",
                "message_id": "evt-1",
                "retry_count": 3,
            },
            metadata={
                "headers": {
                    "id": "rec-1",
                    "type": FailedPositionStatus.EXHAUSTED.value,
                    "stream": failed_stream,
                },
                "domain": {"kind": "read_position", "origin_stream": category},
            },
        )

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app,
                [
                    "eventstore",
                    "dlq",
                    "inspect",
                    str(global_position),
                    "--domain",
                    "x.py",
                ],
            )

        assert result.exit_code == 0, result.output
        assert "old@example.com" in result.output

    def test_inspect_unknown_position_is_usage_error(self, test_domain):
        _register(test_domain)
        _drive_to_exhaustion(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "inspect", "999", "--domain", "x.py"]
            )

        assert result.exit_code == EXIT_USAGE
        assert "No exhausted position 999 found" in result.output

    def test_inspect_unknown_subscription_is_usage_error(self, test_domain):
        _register(test_domain)
        _drive_to_exhaustion(test_domain)

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app,
                [
                    "eventstore",
                    "dlq",
                    "inspect",
                    "1",
                    "--domain",
                    "x.py",
                    "--subscription",
                    "nope",
                ],
            )

        assert result.exit_code == EXIT_USAGE
        assert "No event-store subscription found" in result.output

    def test_inspect_unreadable_event_is_usage_error(self, test_domain):
        """An Exhausted record whose event cannot be re-read (no stream location
        and no origin stream) is a usage error, not a crash."""
        from protean.server.subscription.event_store_subscription import (
            FailedPositionStatus,
        )
        from protean.utils import fqn
        from protean.utils.dlq import failed_positions_stream

        _register(test_domain)
        store = test_domain.event_store.store
        category = User.meta_.stream_category
        failed_stream = failed_positions_stream(
            fqn(AlwaysFailingEventHandler), category
        )
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

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "inspect", "7", "--domain", "x.py"]
            )

        assert result.exit_code == EXIT_USAGE
        assert "Could not re-read the event" in result.output

    def test_list_skips_malformed_records(self, test_domain):
        """A record missing its position is ignored, not counted or crashed on."""
        from protean.server.subscription.event_store_subscription import (
            FailedPositionStatus,
        )
        from protean.utils import fqn
        from protean.utils.dlq import failed_positions_stream

        _register(test_domain)
        store = test_domain.event_store.store
        category = User.meta_.stream_category
        failed_stream = failed_positions_stream(
            fqn(AlwaysFailingEventHandler), category
        )
        store._write(
            failed_stream,
            FailedPositionStatus.EXHAUSTED.value,
            {"message_type": "Test.Registered.v1"},  # no "position"
            metadata={
                "headers": {
                    "id": "rec-bad",
                    "type": FailedPositionStatus.EXHAUSTED.value,
                    "stream": failed_stream,
                },
                "domain": {"kind": "read_position"},
            },
        )

        with patch("protean.cli.eventstore.load_domain", return_value=test_domain):
            result = runner.invoke(
                app, ["eventstore", "dlq", "list", "--domain", "x.py", "--json"]
            )

        assert result.exit_code == 0, result.output
        env = assert_envelope(result.stdout)
        assert env["data"]["subscriptions"] == []
