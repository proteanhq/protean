"""Tests for command enrichment hooks.

Command enrichers are callables registered on the domain that automatically
add custom metadata (``metadata.extensions``) to every command processed
via ``domain.process()`` or ``domain._enrich_command()``.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, String
from protean.utils.eventing import Message
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class Register(BaseCommand):
    user_id: Identifier(identifier=True)
    email: String()


class Activate(BaseCommand):
    user_id: Identifier(identifier=True)


class UserRegistered(BaseEvent):
    user_id: Identifier(identifier=True)


class RegisterHandler(BaseCommandHandler):
    @handle(Register)
    def handle_register(self, command: Register):
        User(id=command.user_id, email=command.email, name="Test")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(Activate, part_of=User)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(RegisterHandler, part_of=User)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Basic enrichment
# ---------------------------------------------------------------------------
class TestBasicCommandEnrichment:
    def test_single_enricher(self, test_domain):
        """A registered enricher populates metadata.extensions on the command."""

        def add_request_id(command):
            return {"request_id": "req-123"}

        test_domain.register_command_enricher(add_request_id)

        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        assert enriched._metadata.extensions == {"request_id": "req-123"}

    def test_multiple_enrichers_merge(self, test_domain):
        """Multiple enrichers contribute to extensions (merge semantics)."""

        def add_user(command):
            return {"user_id": "u-123"}

        def add_tenant(command):
            return {"tenant_id": "t-456"}

        test_domain.register_command_enricher(add_user)
        test_domain.register_command_enricher(add_tenant)

        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        assert enriched._metadata.extensions == {
            "user_id": "u-123",
            "tenant_id": "t-456",
        }

    def test_later_enricher_overrides_earlier(self, test_domain):
        """When two enrichers set the same key, the last one wins."""

        def first(command):
            return {"source": "first"}

        def second(command):
            return {"source": "second"}

        test_domain.register_command_enricher(first)
        test_domain.register_command_enricher(second)

        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        assert enriched._metadata.extensions["source"] == "second"


# ---------------------------------------------------------------------------
# Enricher access to command fields
# ---------------------------------------------------------------------------
class TestEnricherAccess:
    def test_enricher_can_read_command_fields(self, test_domain):
        """Enricher receives the command and can read its payload fields."""

        def mirror_email(command):
            return {"command_email": command.email}

        test_domain.register_command_enricher(mirror_email)

        command = Register(user_id=str(uuid4()), email="test@example.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        assert enriched._metadata.extensions["command_email"] == "test@example.com"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------
class TestCommandEnricherEdgeCases:
    def test_no_enrichers_gives_empty_extensions(self, test_domain):
        """Without enrichers, extensions defaults to empty dict."""
        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        assert enriched._metadata.extensions == {}

    def test_enricher_returning_none(self, test_domain):
        """An enricher returning None is treated as a no-op."""

        def noop(command):
            return None

        test_domain.register_command_enricher(noop)

        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        assert enriched._metadata.extensions == {}

    def test_enricher_returning_empty_dict(self, test_domain):
        """An enricher returning {} is treated as a no-op."""

        def noop(command):
            return {}

        test_domain.register_command_enricher(noop)

        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        assert enriched._metadata.extensions == {}

    def test_error_in_enricher_propagates(self, test_domain):
        """If an enricher raises, the exception propagates."""

        def bad_enricher(command):
            raise ValueError("enricher failed")

        test_domain.register_command_enricher(bad_enricher)

        command = Register(user_id=str(uuid4()), email="a@b.com")
        with pytest.raises(ValueError, match="enricher failed"):
            test_domain._enrich_command(command, asynchronous=True)

    def test_non_callable_raises_error(self, test_domain):
        """Registering a non-callable raises IncorrectUsageError."""
        with pytest.raises(IncorrectUsageError, match="callable"):
            test_domain.register_command_enricher(42)


# ---------------------------------------------------------------------------
# Decorator registration
# ---------------------------------------------------------------------------
class TestDecoratorRegistration:
    def test_command_enricher_decorator(self, test_domain):
        """The @domain.command_enricher decorator registers and returns the fn."""

        @test_domain.command_enricher
        def add_source(command):
            return {"source": "decorator"}

        assert callable(add_source)
        assert add_source.__name__ == "add_source"

        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        assert enriched._metadata.extensions == {"source": "decorator"}


# ---------------------------------------------------------------------------
# Extensions survive through domain.process() and handler
# ---------------------------------------------------------------------------
class TestExtensionsThroughProcessing:
    def test_extensions_reach_event_store(self, test_domain):
        """Command extensions are persisted to the event store."""

        def add_context(command):
            return {"tenant_id": "acme"}

        test_domain.register_command_enricher(add_context)

        identifier = str(uuid4())
        command = Register(user_id=identifier, email="a@b.com")
        test_domain.process(command, asynchronous=False)

        # Read command from event store
        last_msg = test_domain.event_store.store.read_last_message(
            f"test::user:command-{identifier}"
        )
        assert last_msg is not None
        assert last_msg.metadata.extensions == {"tenant_id": "acme"}


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------
class TestSerializationRoundTrip:
    def test_extensions_survive_message_round_trip(self, test_domain):
        """Extensions survive: command → Message → dict → deserialize → extensions."""

        def add_context(command):
            return {"request_id": "r-1", "ip": "127.0.0.1"}

        test_domain.register_command_enricher(add_context)

        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        message = Message.from_domain_object(enriched)
        msg_dict = message.to_dict()

        assert msg_dict["metadata"]["extensions"] == {
            "request_id": "r-1",
            "ip": "127.0.0.1",
        }

        restored = Message.deserialize(msg_dict)
        assert restored.metadata.extensions == {
            "request_id": "r-1",
            "ip": "127.0.0.1",
        }

    def test_empty_extensions_in_serialization(self, test_domain):
        """Empty extensions serialize as {} and deserialize back."""
        command = Register(user_id=str(uuid4()), email="a@b.com")
        enriched = test_domain._enrich_command(command, asynchronous=True)

        message = Message.from_domain_object(enriched)
        msg_dict = message.to_dict()

        assert msg_dict["metadata"]["extensions"] == {}

        restored = Message.deserialize(msg_dict)
        assert restored.metadata.extensions == {}
