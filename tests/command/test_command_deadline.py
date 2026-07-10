"""Tests for command timeout/deadline propagation and expiry rejection."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.domain.command_processor import (
    coerce_timeout,
    raise_if_expired,
    resolve_deadline,
)
from protean.exceptions import CommandExpiredError, IncorrectUsageError
from protean.fields import Identifier, String
from protean.utils.eventing import Message, MessageHeaders
from protean.utils.globals import current_domain, g
from protean.utils.mixins import handle

handled = []


class User(BaseAggregate):
    user_id: Identifier(identifier=True)
    email: String()


class Register(BaseCommand):
    user_id: Identifier(identifier=True)
    email: String()


class Activate(BaseCommand):
    user_id: Identifier(identifier=True)


class Ping(BaseCommand):
    user_id: Identifier(identifier=True)


class UserCommandHandlers(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register):
        handled.append(command.user_id)
        # Dispatch a downstream command to verify deadline propagation.
        current_domain.process(Activate(user_id=command.user_id), asynchronous=False)

    @handle(Activate)
    def activate(self, command: Activate):
        handled.append(("activate", command.user_id))


# Handler that declares a default validity window for its command.
PING_TIMEOUT_SECONDS = 120


class TimedPingHandler(BaseCommandHandler):
    @handle(Ping)
    def ping(self, command: Ping):
        handled.append(("ping", command.user_id))


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(Activate, part_of=User)
    test_domain.register(Ping, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.register(TimedPingHandler, part_of=User, timeout=PING_TIMEOUT_SECONDS)
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def reset_handled():
    handled.clear()
    yield
    handled.clear()


class TestIsExpired:
    def test_no_deadline_is_never_expired(self):
        assert MessageHeaders().is_expired() is False

    def test_future_deadline_is_not_expired(self):
        headers = MessageHeaders(deadline=datetime.now(UTC) + timedelta(minutes=5))
        assert headers.is_expired() is False

    def test_past_deadline_is_expired(self):
        headers = MessageHeaders(deadline=datetime.now(UTC) - timedelta(seconds=1))
        assert headers.is_expired() is True

    def test_naive_deadline_is_treated_as_utc(self):
        # A naive past deadline is still expired.
        past = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=5)
        assert MessageHeaders(deadline=past).is_expired() is True

    def test_explicit_now_reference(self):
        deadline = datetime(2026, 1, 1, tzinfo=UTC)
        before = datetime(2025, 12, 31, tzinfo=UTC)
        after = datetime(2026, 1, 2, tzinfo=UTC)
        headers = MessageHeaders(deadline=deadline)
        assert headers.is_expired(now=before) is False
        assert headers.is_expired(now=after) is True

    def test_naive_now_reference_is_treated_as_utc(self):
        deadline = datetime(2026, 1, 1, tzinfo=UTC)
        headers = MessageHeaders(deadline=deadline)
        # Naive reference times are normalized to UTC, like deadlines.
        assert headers.is_expired(now=datetime(2025, 12, 31)) is False
        assert headers.is_expired(now=datetime(2026, 1, 2)) is True


class TestResolveDeadline:
    def test_neither_returns_none(self):
        assert resolve_deadline(None, None) is None

    def test_timeout_is_converted_to_absolute_deadline(self):
        resolved = resolve_deadline(None, timedelta(seconds=30))
        assert resolved is not None
        assert resolved > datetime.now(UTC)

    def test_explicit_deadline_is_returned(self):
        deadline = datetime.now(UTC) + timedelta(minutes=1)
        assert resolve_deadline(deadline, None) == deadline

    def test_naive_deadline_is_coerced_to_utc(self):
        naive = datetime(2030, 1, 1, 12, 0, 0)
        resolved = resolve_deadline(naive, None)
        assert resolved.tzinfo is UTC

    def test_tz_aware_deadline_is_normalized_to_utc(self):
        # A non-UTC tz-aware deadline is stored as UTC, preserving the instant.
        tz = timezone(timedelta(hours=5, minutes=30))  # IST
        aware = datetime(2030, 1, 1, 17, 30, 0, tzinfo=tz)
        resolved = resolve_deadline(aware, None)
        assert resolved.tzinfo is UTC
        assert resolved == aware  # same instant
        assert resolved == datetime(2030, 1, 1, 12, 0, 0, tzinfo=UTC)

    def test_both_raises(self):
        with pytest.raises(IncorrectUsageError, match="not both"):
            resolve_deadline(datetime.now(UTC), timedelta(seconds=1))

    def test_invalid_timeout_type_raises(self):
        with pytest.raises(IncorrectUsageError, match="timedelta"):
            resolve_deadline(None, 5)

    def test_invalid_deadline_type_raises(self):
        with pytest.raises(IncorrectUsageError, match="datetime"):
            resolve_deadline("2030-01-01", None)


class TestRaiseIfExpired:
    def test_no_headers_is_noop(self):
        raise_if_expired(None, "Cmd")  # should not raise

    def test_future_deadline_is_noop(self):
        headers = MessageHeaders(deadline=datetime.now(UTC) + timedelta(minutes=5))
        raise_if_expired(headers, "Cmd")  # should not raise

    def test_expired_deadline_raises_with_context(self):
        deadline = datetime.now(UTC) - timedelta(seconds=1)
        headers = MessageHeaders(deadline=deadline)
        with pytest.raises(CommandExpiredError) as exc_info:
            raise_if_expired(headers, "MyCommand")
        assert exc_info.value.command_type == "MyCommand"
        assert exc_info.value.deadline == deadline


class TestDeadlineInMetadata:
    def test_deadline_is_stored_in_metadata_when_provided(self, test_domain):
        identifier = str(uuid4())
        deadline = datetime.now(UTC) + timedelta(minutes=5)
        command = Register(user_id=identifier, email="john@example.com")

        test_domain.process(command, deadline=deadline)

        messages = test_domain.event_store.store.read("user:command")
        assert len(messages) >= 1
        assert messages[0].metadata.headers.deadline == deadline

    def test_timeout_is_stored_as_absolute_deadline(self, test_domain):
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        before = datetime.now(UTC)
        test_domain.process(command, timeout=timedelta(minutes=10))

        messages = test_domain.event_store.store.read("user:command")
        assert len(messages) >= 1
        stored = messages[0].metadata.headers.deadline
        assert stored is not None
        assert stored > before

    def test_deadline_is_none_when_not_provided(self, test_domain):
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        test_domain.process(command)

        messages = test_domain.event_store.store.read("user:command")
        assert len(messages) >= 1
        assert messages[0].metadata.headers.deadline is None

    def test_deadline_round_trips_through_event_store(self, test_domain):
        identifier = str(uuid4())
        deadline = datetime.now(UTC) + timedelta(hours=1)
        command = Register(user_id=identifier, email="john@example.com")

        test_domain.process(command, deadline=deadline)

        message = test_domain.event_store.store.read_last_message(
            f"test::user:command-{identifier}"
        )
        assert message is not None
        assert message.metadata.headers.deadline == deadline

    def test_both_deadline_and_timeout_raises(self, test_domain):
        command = Register(user_id=str(uuid4()), email="john@example.com")
        with pytest.raises(IncorrectUsageError, match="not both"):
            test_domain.process(
                command,
                deadline=datetime.now(UTC),
                timeout=timedelta(seconds=1),
            )


class TestSyncDeadlineEnforcement:
    def test_expired_command_is_rejected_before_handler_runs(self, test_domain):
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")
        past = datetime.now(UTC) - timedelta(seconds=1)

        with pytest.raises(CommandExpiredError) as exc_info:
            test_domain.process(command, asynchronous=False, deadline=past)

        assert exc_info.value.command_type == Register.__type__
        assert handled == []  # handler never ran

    def test_non_expired_command_runs_normally(self, test_domain):
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")
        future = datetime.now(UTC) + timedelta(minutes=5)

        test_domain.process(command, asynchronous=False, deadline=future)

        assert identifier in handled


class TestDeadlinePropagation:
    def test_downstream_command_inherits_deadline(self, test_domain):
        identifier = str(uuid4())
        deadline = datetime.now(UTC) + timedelta(minutes=5)
        command = Register(user_id=identifier, email="john@example.com")

        # Register handler dispatches Activate synchronously within its context.
        test_domain.process(command, asynchronous=False, deadline=deadline)

        activate_message = test_domain.event_store.store.read_last_message(
            f"test::user:command-{identifier}"
        )
        # The last command written for this aggregate is Activate; it must
        # carry the deadline inherited from Register.
        assert activate_message.metadata.headers.type == Activate.__type__
        assert activate_message.metadata.headers.deadline == deadline

    def test_context_deadline_is_inherited_when_no_explicit_deadline(self, test_domain):
        # With a parent command in context carrying a deadline, a new command
        # enriched without an explicit deadline inherits the context's deadline.
        context_deadline = datetime.now(UTC) + timedelta(minutes=10)
        parent = test_domain._command_processor.enrich(
            Register(user_id=str(uuid4()), email="parent@example.com"),
            asynchronous=True,
            deadline=context_deadline,
        )
        g.message_in_context = Message.from_domain_object(parent)
        try:
            child = test_domain._command_processor.enrich(
                Activate(user_id=str(uuid4())), asynchronous=True
            )
        finally:
            g.pop("message_in_context", None)

        assert child._metadata.headers.deadline == context_deadline

    def test_explicit_deadline_wins_over_context_deadline(self, test_domain):
        # When the context carries a deadline AND the caller passes an explicit
        # one, the explicit deadline wins for the new command.
        context_deadline = datetime.now(UTC) + timedelta(minutes=10)
        explicit = datetime.now(UTC) + timedelta(minutes=1)
        parent = test_domain._command_processor.enrich(
            Register(user_id=str(uuid4()), email="parent@example.com"),
            asynchronous=True,
            deadline=context_deadline,
        )
        g.message_in_context = Message.from_domain_object(parent)
        try:
            child = test_domain._command_processor.enrich(
                Activate(user_id=str(uuid4())), asynchronous=True, deadline=explicit
            )
        finally:
            g.pop("message_in_context", None)

        assert child._metadata.headers.deadline == explicit


class TestCoerceTimeout:
    def test_seconds_number_becomes_timedelta(self):
        assert coerce_timeout(30) == timedelta(seconds=30)
        assert coerce_timeout(1.5) == timedelta(seconds=1.5)

    def test_timedelta_passes_through(self):
        td = timedelta(minutes=2)
        assert coerce_timeout(td) is td

    def test_bool_is_rejected(self):
        with pytest.raises(IncorrectUsageError, match="number of seconds"):
            coerce_timeout(True)

    def test_string_is_rejected(self):
        with pytest.raises(IncorrectUsageError, match="number of seconds"):
            coerce_timeout("30")


class TestDefaultTimeout:
    def test_domain_config_default_applies(self, test_domain):
        test_domain.config["command_default_timeout"] = 60
        before = datetime.now(UTC)
        command = Register(user_id=str(uuid4()), email="john@example.com")

        test_domain.process(command)

        stored = test_domain.event_store.store.read("user:command")[0]
        deadline = stored.metadata.headers.deadline
        assert deadline is not None
        # ~now + 60s (allow scheduling slack)
        assert timedelta(seconds=55) <= (deadline - before) <= timedelta(seconds=65)

    def test_handler_timeout_option_applies(self, test_domain):
        before = datetime.now(UTC)
        command = Ping(user_id=str(uuid4()))

        test_domain.process(command)

        stored = test_domain.event_store.store.read("user:command")[0]
        deadline = stored.metadata.headers.deadline
        assert deadline is not None
        assert (
            timedelta(seconds=PING_TIMEOUT_SECONDS - 5)
            <= (deadline - before)
            <= timedelta(seconds=PING_TIMEOUT_SECONDS + 5)
        )

    def test_handler_option_overrides_config_default(self, test_domain):
        # Config sets 60s, but Ping's handler declares 120s — handler wins.
        test_domain.config["command_default_timeout"] = 60
        before = datetime.now(UTC)

        test_domain.process(Ping(user_id=str(uuid4())))

        stored = test_domain.event_store.store.read("user:command")[0]
        deadline = stored.metadata.headers.deadline
        assert (deadline - before) > timedelta(seconds=90)

    def test_explicit_deadline_overrides_defaults(self, test_domain):
        test_domain.config["command_default_timeout"] = 60
        explicit = datetime.now(UTC) + timedelta(hours=1)

        test_domain.process(Ping(user_id=str(uuid4())), deadline=explicit)

        stored = test_domain.event_store.store.read("user:command")[0]
        assert stored.metadata.headers.deadline == explicit

    def test_no_default_means_no_deadline(self, test_domain):
        # Register's handler declares no timeout and config default is unset.
        test_domain.process(Register(user_id=str(uuid4()), email="a@b.com"))

        stored = test_domain.event_store.store.read("user:command")[0]
        assert stored.metadata.headers.deadline is None
