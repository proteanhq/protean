"""Tests for command idempotency key propagation and submission-level dedup.

Phase 1: Verify that the idempotency_key flows through MessageHeaders,
domain.process(), event store serialization, and back through deserialization.

Phase 2 (unit tests): Verify DuplicateCommandError, no-Redis fallback,
and raise_on_duplicate behavior without Redis.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import DuplicateCommandError
from protean.fields import Identifier, String
from protean.utils.mixins import handle


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String()


class UserCommandHandlers(BaseCommandHandler):
    @handle(Register)
    def register(self, command: Register):
        # Return the idempotency key to prove it's accessible in the handler
        return {
            "user_id": command.user_id,
            "idempotency_key": command._metadata.headers.idempotency_key,
        }


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.init(traverse=False)


class TestIdempotencyKeyInHeaders:
    def test_idempotency_key_is_set_in_command_metadata_when_provided(
        self, test_domain
    ):
        """When an idempotency key is passed to domain.process(),
        it should be stored in the command's metadata headers."""
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        test_domain.process(command, idempotency_key="key-1")

        messages = test_domain.event_store.store.read("user:command")
        assert len(messages) == 1
        assert messages[0].metadata.headers.idempotency_key == "key-1"

    def test_idempotency_key_is_none_when_not_provided(self, test_domain):
        """When no idempotency key is provided, the field should be None."""
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        test_domain.process(command)

        messages = test_domain.event_store.store.read("user:command")
        assert len(messages) == 1
        assert messages[0].metadata.headers.idempotency_key is None

    def test_idempotency_key_round_trips_through_event_store(self, test_domain):
        """The idempotency key should survive serialization to the event store
        and deserialization back into a Message object."""
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        test_domain.process(command, idempotency_key="round-trip-key")

        # Read back from event store as Message
        message = test_domain.event_store.store.read_last_message(
            f"test::user:command-{identifier}"
        )
        assert message is not None
        assert message.metadata.headers.idempotency_key == "round-trip-key"

    def test_idempotency_key_available_in_handler(self, test_domain):
        """When processing synchronously, the handler should be able to access
        the idempotency key from the command's metadata."""
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        result = test_domain.process(command, idempotency_key="handler-key")

        assert result["idempotency_key"] == "handler-key"

    def test_idempotency_key_available_in_deserialized_message(self, test_domain):
        """After writing a command with a key, reading it back as a Message
        and converting to a domain object should preserve the key."""
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        test_domain.process(command, idempotency_key="deser-key")

        # Read back and convert to domain object
        message = test_domain.event_store.store.read_last_message(
            f"test::user:command-{identifier}"
        )
        domain_object = message.to_domain_object()
        assert domain_object._metadata.headers.idempotency_key == "deser-key"

    def test_enrich_command_sets_idempotency_key(self, test_domain):
        """The _enrich_command method should propagate the idempotency key
        into the MessageHeaders."""
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        enriched = test_domain._enrich_command(
            command, asynchronous=True, idempotency_key="enrich-key"
        )
        assert enriched._metadata.headers.idempotency_key == "enrich-key"

    def test_enrich_command_without_idempotency_key(self, test_domain):
        """Without an idempotency key, _enrich_command should leave the field None."""
        identifier = str(uuid4())
        command = Register(user_id=identifier, email="john@example.com")

        enriched = test_domain._enrich_command(command, asynchronous=True)
        assert enriched._metadata.headers.idempotency_key is None


# ==============================================================================
# Phase 2 unit tests — no Redis needed
# ==============================================================================


class TestDuplicateCommandError:
    def test_duplicate_command_error_has_original_result(self):
        """DuplicateCommandError should carry the original result."""
        error = DuplicateCommandError("duplicate", original_result={"counter": 1})
        assert error.original_result == {"counter": 1}
        assert str(error) == "duplicate"

    def test_duplicate_command_error_with_none_result(self):
        """DuplicateCommandError can have None as original_result."""
        error = DuplicateCommandError("duplicate")
        assert error.original_result is None


class TestNoRedisIdempotencyBehavior:
    """When Redis is not configured, idempotency dedup is disabled.
    process() should work normally without any errors."""

    def test_process_without_idempotency_key_always_proceeds(self, test_domain):
        """Two identical process() calls without a key should both succeed."""
        id1 = str(uuid4())
        result1 = test_domain.process(Register(user_id=id1, email="a@example.com"))
        id2 = str(uuid4())
        result2 = test_domain.process(Register(user_id=id2, email="b@example.com"))

        # Both return handler results (no dedup)
        assert result1 is not None
        assert result2 is not None

    def test_raise_on_duplicate_without_key_has_no_effect(self, test_domain):
        """raise_on_duplicate=True with no key should not raise."""
        identifier = str(uuid4())
        result = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            raise_on_duplicate=True,
        )
        # Should return normally (handler result)
        assert result is not None

    def test_no_redis_config_bypasses_dedup(self, test_domain):
        """Without Redis configured, process() with an idempotency key
        works normally — no dedup, no errors."""
        id1 = str(uuid4())
        result1 = test_domain.process(
            Register(user_id=id1, email="a@example.com"),
            idempotency_key="key-1",
        )
        id2 = str(uuid4())
        result2 = test_domain.process(
            Register(user_id=id2, email="b@example.com"),
            idempotency_key="key-2",
        )

        # Both should process — no Redis means no dedup
        assert result1 is not None
        assert result2 is not None
