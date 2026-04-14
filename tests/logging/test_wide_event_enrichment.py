"""Tests for wide event enrichment via bind_event_context().

Verifies that:
- Application-provided fields appear in the wide event
- Multiple bind calls merge correctly
- Later bind calls overwrite conflicting keys
- unbind removes specific fields
- bind_event_context outside handler is a no-op
- Context is cleared between handler invocations
- App context cannot overwrite framework-reserved fields
- Outer structlog context is preserved across handler invocations
- LogRecord-reserved attribute names are stripped from app context
"""

import logging
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.utils.logging import bind_event_context, unbind_event_context
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# --- Domain elements ---


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String()

    def activate(self) -> None:
        self.raise_(AccountActivated(account_id=self.account_id))


class AccountActivated(BaseEvent):
    account_id = Identifier()


class CreateAccount(BaseCommand):
    account_id = Identifier(identifier=True)
    name = String()


class BindContextHandler(BaseCommandHandler):
    @handle(CreateAccount)
    def handle_create(self, command: CreateAccount) -> None:
        bind_event_context(
            user_tier="premium",
            order_total=9999,
        )


class MultipleBindHandler(BaseCommandHandler):
    @handle(CreateAccount)
    def handle_create(self, command: CreateAccount) -> None:
        bind_event_context(a=1)
        bind_event_context(b=2)


class OverwriteBindHandler(BaseCommandHandler):
    @handle(CreateAccount)
    def handle_create(self, command: CreateAccount) -> None:
        bind_event_context(x=1)
        bind_event_context(x=2)


class UnbindHandler(BaseCommandHandler):
    @handle(CreateAccount)
    def handle_create(self, command: CreateAccount) -> None:
        bind_event_context(a=1, b=2)
        unbind_event_context("a")


class FrameworkOverrideHandler(BaseCommandHandler):
    @handle(CreateAccount)
    def handle_create(self, command: CreateAccount) -> None:
        bind_event_context(kind="hacked", duration_ms=-1)


class LogRecordCollisionHandler(BaseCommandHandler):
    @handle(CreateAccount)
    def handle_create(self, command: CreateAccount) -> None:
        # Bind keys that collide with stdlib LogRecord attributes
        bind_event_context(name="bad", levelno=99, msg="bad", safe_key="safe_value")


class BindContextEventHandler(BaseEventHandler):
    @handle(AccountActivated)
    def on_activated(self, event: AccountActivated) -> None:
        # This handler does NOT call bind_event_context
        pass


class BindInCommandHandler(BaseCommandHandler):
    """Handler that binds context and raises an event."""

    @handle(CreateAccount)
    def handle_create(self, command: CreateAccount) -> None:
        bind_event_context(user_id="abc")
        repo = current_domain.repository_for(Account)
        account = Account(account_id=command.account_id, name=command.name)
        account.activate()
        repo.add(account)


def _access_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "protean.access"]


class TestBindEventContextAppearsInWideEvent:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountActivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(BindContextHandler, part_of=Account)
        test_domain.init(traverse=False)

    def test_bind_event_context_appears_in_wide_event(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateAccount(account_id=str(uuid4()), name="Test User")
            )

        records = _access_records(caplog)
        assert len(records) >= 1

        record = records[0]
        assert record.user_tier == "premium"
        assert record.order_total == 9999


class TestMultipleBindCallsMerge:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountActivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(MultipleBindHandler, part_of=Account)
        test_domain.init(traverse=False)

    def test_multiple_bind_calls_merge(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateAccount(account_id=str(uuid4()), name="Merge Test")
            )

        records = _access_records(caplog)
        assert len(records) >= 1

        record = records[0]
        assert record.a == 1
        assert record.b == 2


class TestBindOverwritesOnConflict:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountActivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(OverwriteBindHandler, part_of=Account)
        test_domain.init(traverse=False)

    def test_bind_overwrites_on_conflict(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateAccount(account_id=str(uuid4()), name="Overwrite Test")
            )

        records = _access_records(caplog)
        assert len(records) >= 1
        assert records[0].x == 2


class TestUnbindRemovesField:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountActivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(UnbindHandler, part_of=Account)
        test_domain.init(traverse=False)

    def test_unbind_removes_field(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateAccount(account_id=str(uuid4()), name="Unbind Test")
            )

        records = _access_records(caplog)
        assert len(records) >= 1

        record = records[0]
        assert not hasattr(record, "a")
        assert record.b == 2


class TestBindOutsideHandlerIsNoop:
    def test_bind_outside_handler_is_noop(self):
        """Calling bind_event_context outside any handler should not raise."""
        bind_event_context(foo="bar")
        # No error expected — it's a no-op in terms of side effects


class TestContextClearedBetweenHandlers:
    """Context from one handler does not leak into the next."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountActivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(BindInCommandHandler, part_of=Account)
        test_domain.register(BindContextEventHandler, part_of=Account)
        test_domain.init(traverse=False)

    def test_context_is_cleared_between_handlers(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateAccount(account_id=str(uuid4()), name="Clear Test")
            )

        records = _access_records(caplog)
        # Find the event handler record (should NOT have user_id)
        event_records = [r for r in records if r.kind == "event"]
        if event_records:
            assert not hasattr(event_records[0], "user_id"), (
                "user_id from command handler should not leak into event handler"
            )


class TestAppContextDoesNotOverwriteFrameworkFields:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountActivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(FrameworkOverrideHandler, part_of=Account)
        test_domain.init(traverse=False)

    def test_app_context_does_not_overwrite_framework_fields(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateAccount(account_id=str(uuid4()), name="Override Test")
            )

        records = _access_records(caplog)
        assert len(records) >= 1

        record = records[0]
        # Framework fields should take precedence
        assert record.kind == "command"  # NOT "hacked"
        assert record.duration_ms > 0  # NOT -1


class TestOuterContextPreservedAcrossHandlers:
    """Outer structlog context (bound via add_context) is restored after handler."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountActivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(BindContextHandler, part_of=Account)
        test_domain.init(traverse=False)

    def test_outer_context_preserved(self, test_domain, caplog):
        import structlog

        # Bind outer context before handler invocation
        structlog.contextvars.bind_contextvars(request_id="req-999")

        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateAccount(account_id=str(uuid4()), name="Preserve Test")
            )

        # Outer context should be restored after handler completes
        ctx = structlog.contextvars.get_contextvars()
        assert ctx.get("request_id") == "req-999", (
            "Outer structlog context should be preserved after handler invocation"
        )

        # Clean up
        structlog.contextvars.clear_contextvars()


class TestLogRecordReservedKeysStripped:
    """App context keys that collide with LogRecord attrs are stripped."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.register(AccountActivated, part_of=Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(LogRecordCollisionHandler, part_of=Account)
        test_domain.init(traverse=False)

    def test_logrecord_reserved_keys_stripped(self, test_domain, caplog):
        """Binding keys that collide with LogRecord attributes should not
        cause errors — they are silently stripped."""
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateAccount(account_id=str(uuid4()), name="Collision Test")
            )

        # The handler should complete successfully (no KeyError)
        records = _access_records(caplog)
        assert len(records) >= 1
        assert records[0].status == "ok"
        # The safe key should still be present
        assert records[0].safe_key == "safe_value"
