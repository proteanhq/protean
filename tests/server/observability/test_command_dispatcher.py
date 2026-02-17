"""Tests for the CommandDispatcher class."""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.engine import CommandDispatcher
from protean.utils.eventing import Message
from protean.utils.mixins import handle


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class Register(BaseCommand):
    user_id: Identifier()
    email: String()


class Activate(BaseCommand):
    user_id: Identifier()


class Deactivate(BaseCommand):
    user_id: Identifier()


register_calls = []
activate_calls = []


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register) -> None:
        register_calls.append(command)

    @handle(Activate)
    def activate(self, command: Activate) -> None:
        activate_calls.append(command)


class FailingCommandHandler(BaseCommandHandler):
    @handle(Deactivate)
    def deactivate(self, command: Deactivate) -> None:
        raise ValueError("Handler failed")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Activate, part_of=User)
    test_domain.register(Deactivate, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.register(FailingCommandHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def reset_call_tracking():
    register_calls.clear()
    activate_calls.clear()
    yield


class TestCommandDispatcherIdentity:
    def test_name_includes_stream_category(self, test_domain):
        dispatcher = CommandDispatcher(
            "test::user:command",
            {},
            UserCommandHandler,
        )
        assert dispatcher.__name__ == "Commands:test::user:command"
        assert dispatcher.__qualname__ == "Commands:test::user:command"

    def test_module_is_engine(self, test_domain):
        dispatcher = CommandDispatcher(
            "test::user:command",
            {},
            UserCommandHandler,
        )
        assert dispatcher.__module__ == "protean.server.engine"

    def test_meta_copied_from_source_handler(self, test_domain):
        dispatcher = CommandDispatcher(
            "test::user:command",
            {},
            UserCommandHandler,
        )
        assert dispatcher.meta_ is UserCommandHandler.meta_


class TestCommandDispatcherRouting:
    def test_routes_register_command_to_correct_handler(self, test_domain):
        """CommandDispatcher routes Register command to UserCommandHandler."""
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="test@example.com")
        enriched = test_domain._enrich_command(command, True)
        message = Message.from_domain_object(enriched)

        engine = Engine(domain=test_domain, test_mode=True)

        # Find the dispatcher from subscriptions
        subscription_key = "commands:test::user:command"
        subscription = engine._subscriptions[subscription_key]
        dispatcher = subscription.handler

        assert isinstance(dispatcher, CommandDispatcher)
        dispatcher._handle(message)
        assert len(register_calls) == 1

    def test_routes_activate_command_to_correct_handler(self, test_domain):
        """CommandDispatcher routes Activate command to UserCommandHandler."""
        identifier = str(uuid4())
        command = Activate(user_id=identifier)
        enriched = test_domain._enrich_command(command, True)
        message = Message.from_domain_object(enriched)

        engine = Engine(domain=test_domain, test_mode=True)

        subscription_key = "commands:test::user:command"
        dispatcher = engine._subscriptions[subscription_key].handler

        dispatcher._handle(message)
        assert len(activate_calls) == 1

    def test_unknown_command_returns_none_with_warning(self, test_domain, caplog):
        """_handle returns None for unregistered command type."""
        dispatcher = CommandDispatcher(
            "test::user:command",
            {},  # Empty handler map
            UserCommandHandler,
        )

        identifier = str(uuid4())
        command = Register(user_id=identifier, email="test@example.com")
        enriched = test_domain._enrich_command(command, True)
        message = Message.from_domain_object(enriched)

        result = dispatcher._handle(message)
        assert result is None
        assert "No command handler registered" in caplog.text


class TestCommandDispatcherResolveHandler:
    def test_resolve_handler_returns_class_for_known_command(self, test_domain):
        engine = Engine(domain=test_domain, test_mode=True)
        subscription_key = "commands:test::user:command"
        dispatcher = engine._subscriptions[subscription_key].handler

        identifier = str(uuid4())
        command = Register(user_id=identifier, email="test@example.com")
        enriched = test_domain._enrich_command(command, True)
        message = Message.from_domain_object(enriched)

        resolved = dispatcher.resolve_handler(message)
        assert resolved is UserCommandHandler

    def test_resolve_handler_returns_none_for_unknown(self, test_domain):
        dispatcher = CommandDispatcher(
            "test::user:command",
            {},  # Empty handler map
            UserCommandHandler,
        )

        identifier = str(uuid4())
        command = Register(user_id=identifier, email="test@example.com")
        enriched = test_domain._enrich_command(command, True)
        message = Message.from_domain_object(enriched)

        resolved = dispatcher.resolve_handler(message)
        assert resolved is None


class TestCommandDispatcherErrorHandling:
    def test_handle_error_delegates_to_resolved_handler(self, test_domain):
        """handle_error calls the resolved handler's handle_error."""
        engine = Engine(domain=test_domain, test_mode=True)
        subscription_key = "commands:test::user:command"
        dispatcher = engine._subscriptions[subscription_key].handler

        # Route a command first to set _last_resolved_handler
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="test@example.com")
        enriched = test_domain._enrich_command(command, True)
        message = Message.from_domain_object(enriched)
        dispatcher._handle(message)

        # handle_error should not raise
        dispatcher.handle_error(Exception("test"), message)

    def test_handle_error_noop_without_resolution(self, test_domain):
        """handle_error does nothing when _last_resolved_handler is None."""
        dispatcher = CommandDispatcher(
            "test::user:command",
            {},
            UserCommandHandler,
        )
        # No previous _handle call, so _last_resolved_handler is None
        dispatcher.handle_error(Exception("test"), None)  # Should not raise


class TestCommandDispatcherCaching:
    def test_resolve_then_handle_does_not_double_deserialize(self, test_domain):
        """After resolve_handler, _handle should reuse the cached domain object."""
        engine = Engine(domain=test_domain, test_mode=True)
        subscription_key = "commands:test::user:command"
        dispatcher = engine._subscriptions[subscription_key].handler

        identifier = str(uuid4())
        command = Register(user_id=identifier, email="test@example.com")
        enriched = test_domain._enrich_command(command, True)
        message = Message.from_domain_object(enriched)

        # Call resolve_handler first (as engine.handle_message does)
        resolved = dispatcher.resolve_handler(message)
        assert resolved is UserCommandHandler
        assert dispatcher._last_resolved_item is not None

        # _handle should use cached item
        dispatcher._handle(message)
        assert dispatcher._last_resolved_item is None  # Cleared after use
        assert len(register_calls) == 1


class TestEngineGroupsCommandsByStream:
    def test_one_subscription_per_stream_category(self, test_domain):
        """Engine creates exactly one subscription per stream category, not per handler."""
        engine = Engine(domain=test_domain, test_mode=True)

        # Both UserCommandHandler and FailingCommandHandler are part_of=User
        # so they share the same stream category
        command_subscriptions = [
            key for key in engine._subscriptions if key.startswith("commands:")
        ]
        assert len(command_subscriptions) == 1
        assert command_subscriptions[0] == "commands:test::user:command"
