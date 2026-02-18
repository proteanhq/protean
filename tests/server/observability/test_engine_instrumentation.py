"""Tests for Engine observability instrumentation.

Verifies that handle_message emits the correct trace events
(handler.started, handler.completed, handler.failed) via the emitter.
"""

from unittest.mock import Mock
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean import apply
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.engine import CommandDispatcher
from protean.utils.eventing import Message
from protean.utils.globals import g
from protean.utils.mixins import handle


# Domain elements for testing
class Registered(BaseEvent):
    id: Identifier()
    email: String()


class Register(BaseCommand):
    user_id: Identifier()
    email: String()


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email


handler_calls = []


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        handler_calls.append(event)


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        handler_calls.append(command)


class FailingEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        raise RuntimeError("Handler exploded")


@pytest.fixture(autouse=True)
def reset_calls():
    handler_calls.clear()
    yield


def _make_event_message(test_domain):
    """Helper to create a valid event Message."""
    identifier = str(uuid4())
    user = User(id=identifier, email="test@example.com", name="Test")
    user.raise_(Registered(id=identifier, email="test@example.com"))
    return Message.from_domain_object(user._events[-1])


def _make_command_message(test_domain):
    """Helper to create a valid command Message."""
    identifier = str(uuid4())
    command = Register(user_id=identifier, email="test@example.com")
    enriched = test_domain._enrich_command(command, True)
    return Message.from_domain_object(enriched)


class TestHandlerStartedTrace:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_handler_started_emitted_before_processing(self, test_domain):
        """handle_message emits handler.started trace."""
        engine = Engine(domain=test_domain, test_mode=True)
        engine.emitter = Mock()

        message = _make_event_message(test_domain)
        await engine.handle_message(UserEventHandler, message)

        # Find handler.started call
        started_calls = [
            c
            for c in engine.emitter.emit.call_args_list
            if c.kwargs.get("event") == "handler.started"
        ]
        assert len(started_calls) == 1
        call = started_calls[0]
        assert call.kwargs["handler"] == "UserEventHandler"
        assert call.kwargs["message_type"] != "unknown"
        assert call.kwargs["stream"] != "unknown"


class TestHandlerCompletedTrace:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_handler_completed_emitted_on_success(self, test_domain):
        """handle_message emits handler.completed with duration on success."""
        engine = Engine(domain=test_domain, test_mode=True)
        engine.emitter = Mock()

        message = _make_event_message(test_domain)
        result = await engine.handle_message(UserEventHandler, message)

        assert result is True

        completed_calls = [
            c
            for c in engine.emitter.emit.call_args_list
            if c.kwargs.get("event") == "handler.completed"
        ]
        assert len(completed_calls) == 1
        call = completed_calls[0]
        assert call.kwargs["handler"] == "UserEventHandler"
        assert call.kwargs["duration_ms"] is not None
        assert call.kwargs["duration_ms"] >= 0


class TestHandlerFailedTrace:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_handler_failed_emitted_on_exception(self, test_domain):
        """handle_message emits handler.failed with error on exception."""
        engine = Engine(domain=test_domain, test_mode=True)
        engine.emitter = Mock()

        message = _make_event_message(test_domain)
        result = await engine.handle_message(FailingEventHandler, message)

        assert result is False

        failed_calls = [
            c
            for c in engine.emitter.emit.call_args_list
            if c.kwargs.get("event") == "handler.failed"
        ]
        assert len(failed_calls) == 1
        call = failed_calls[0]
        assert call.kwargs["status"] == "error"
        assert call.kwargs["handler"] == "FailingEventHandler"
        assert "Handler exploded" in call.kwargs["error"]
        assert call.kwargs["duration_ms"] is not None


class TestCommandDispatcherHandlerName:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Register, part_of=User)
        test_domain.register(UserCommandHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_resolved_handler_name_for_dispatcher(self, test_domain):
        """For CommandDispatcher, emitter receives resolved handler name, not dispatcher name."""
        engine = Engine(domain=test_domain, test_mode=True)
        engine.emitter = Mock()

        # Get the dispatcher from the subscription
        subscription_key = "commands:test::user:command"
        dispatcher = engine._subscriptions[subscription_key].handler
        assert isinstance(dispatcher, CommandDispatcher)

        message = _make_command_message(test_domain)
        await engine.handle_message(dispatcher, message)

        started_calls = [
            c
            for c in engine.emitter.emit.call_args_list
            if c.kwargs.get("event") == "handler.started"
        ]
        assert len(started_calls) == 1
        # Should be the specific handler name, not "Commands:test::user:command"
        assert started_calls[0].kwargs["handler"] == "UserCommandHandler"


class TestMessageContextCleanup:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.register(FailingEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_message_context_cleaned_up_on_success(self, test_domain):
        """g.message_in_context is cleared after successful processing."""
        engine = Engine(domain=test_domain, test_mode=True)
        engine.emitter = Mock()

        message = _make_event_message(test_domain)
        await engine.handle_message(UserEventHandler, message)

        # After handle_message returns, the domain context is exited
        # and g should be clean. Verify by entering a fresh context.
        with test_domain.domain_context():
            assert not hasattr(g, "message_in_context") or g.message_in_context is None

    @pytest.mark.asyncio
    async def test_message_context_cleaned_up_on_failure(self, test_domain):
        """g.message_in_context is cleared after failed processing."""
        engine = Engine(domain=test_domain, test_mode=True)
        engine.emitter = Mock()

        message = _make_event_message(test_domain)
        await engine.handle_message(FailingEventHandler, message)

        with test_domain.domain_context():
            assert not hasattr(g, "message_in_context") or g.message_in_context is None


class TestShutdownSkip:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Registered, part_of=User)
        test_domain.register(UserEventHandler, part_of=User)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_skips_when_shutting_down(self, test_domain):
        """Returns False without emitting when engine is shutting down."""
        engine = Engine(domain=test_domain, test_mode=True)
        engine.emitter = Mock()
        engine.shutting_down = True

        message = _make_event_message(test_domain)
        result = await engine.handle_message(UserEventHandler, message)

        assert result is False
        engine.emitter.emit.assert_not_called()
