"""Redis integration tests for command idempotency (Phase 2).

All tests in this module require a running Redis instance
and the ``--redis`` pytest flag.
"""

import time
from uuid import uuid4

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import DuplicateCommandError
from protean.fields import Identifier, String
from protean.utils.mixins import handle

# Use a dedicated Redis database for idempotency tests (db 5)
REDIS_IDEMPOTENCY_URL = "redis://localhost:6379/5"

pytestmark = pytest.mark.redis


# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------

call_counter = 0


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
        global call_counter
        call_counter += 1
        return {"user_id": command.user_id, "counter": call_counter}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    # Configure idempotency with Redis
    test_domain.config["idempotency"]["redis_url"] = REDIS_IDEMPOTENCY_URL
    # Reset the lazily-initialized store so it picks up new config
    test_domain._idempotency_store = None

    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandlers, part_of=User)
    test_domain.init(traverse=False)

    yield

    # Cleanup Redis
    test_domain.idempotency_store.flush()


@pytest.fixture(autouse=True)
def reset_counter():
    global call_counter
    call_counter = 0
    yield


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSyncDuplication:
    def test_sync_duplicate_returns_cached_result(self, test_domain):
        """Processing a command twice with the same key should return
        the cached result and invoke the handler only once."""
        global call_counter
        identifier = str(uuid4())

        result1 = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            idempotency_key="sync-dup-1",
        )
        result2 = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            idempotency_key="sync-dup-1",
        )

        assert result1 == result2
        assert call_counter == 1  # Handler called only once

    def test_different_keys_are_processed_independently(self, test_domain):
        """Two commands with different idempotency keys should both
        be processed."""
        global call_counter

        test_domain.process(
            Register(user_id=str(uuid4()), email="a@example.com"),
            idempotency_key="key-A",
        )
        test_domain.process(
            Register(user_id=str(uuid4()), email="b@example.com"),
            idempotency_key="key-B",
        )

        assert call_counter == 2

    def test_raise_on_duplicate_raises_exception(self, test_domain):
        """raise_on_duplicate=True should raise DuplicateCommandError
        on the second call with the same key."""
        identifier = str(uuid4())
        original_result = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            idempotency_key="raise-key-1",
        )

        with pytest.raises(DuplicateCommandError) as exc_info:
            test_domain.process(
                Register(user_id=identifier, email="a@example.com"),
                idempotency_key="raise-key-1",
                raise_on_duplicate=True,
            )

        assert exc_info.value.original_result == original_result

    def test_raise_on_duplicate_on_first_call_does_not_raise(self, test_domain):
        """raise_on_duplicate=True on a fresh key should not raise."""
        identifier = str(uuid4())
        result = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            idempotency_key="fresh-raise-key",
            raise_on_duplicate=True,
        )
        assert result is not None


class TestAsyncDuplication:
    def test_async_duplicate_returns_cached_position(self, test_domain):
        """For async processing, the cached value is the event store position."""
        identifier = str(uuid4())

        position1 = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            asynchronous=True,
            idempotency_key="async-dup-1",
        )
        position2 = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            asynchronous=True,
            idempotency_key="async-dup-1",
        )

        assert position1 == position2
        # The command should only be appended to event store once
        messages = test_domain.event_store.store.read("user:command")
        assert len(messages) == 1


class TestFailureRecovery:
    def test_failed_sync_processing_allows_retry(self, test_domain):
        """If the handler fails, the error record has a short TTL,
        and a retry with the same key should succeed."""
        # Configure very short error TTL for testing
        test_domain.config["idempotency"]["error_ttl"] = 1
        test_domain._idempotency_store = None  # Reset store

        # Use a separate command/handler pair to avoid "multiple handlers" conflict
        class Activate(BaseCommand):
            user_id = Identifier(identifier=True)

        fail_once = {"should_fail": True}

        class ActivateHandlers(BaseCommandHandler):
            @handle(Activate)
            def activate(self, command: Activate):
                if fail_once["should_fail"]:
                    fail_once["should_fail"] = False
                    raise RuntimeError("Transient error")
                return {"user_id": command.user_id, "status": "success"}

        test_domain.register(Activate, part_of=User)
        test_domain.register(ActivateHandlers, part_of=User)
        test_domain.init(traverse=False)

        identifier = str(uuid4())

        # First call: handler fails
        with pytest.raises(RuntimeError, match="Transient error"):
            test_domain.process(
                Activate(user_id=identifier),
                idempotency_key="fail-retry-key",
            )

        # Wait for the error TTL to expire
        time.sleep(1.5)

        # Retry: handler succeeds
        result = test_domain.process(
            Activate(user_id=identifier),
            idempotency_key="fail-retry-key",
        )
        assert result["status"] == "success"


class TestTTLExpiry:
    def test_idempotency_store_ttl_expiry(self, test_domain):
        """After the TTL expires, the same key should be processed again."""
        global call_counter

        # Configure very short TTL for testing
        test_domain.config["idempotency"]["ttl"] = 1
        test_domain._idempotency_store = None  # Reset store

        identifier = str(uuid4())

        test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            idempotency_key="ttl-key",
        )
        assert call_counter == 1

        # Wait for TTL to expire
        time.sleep(1.5)

        test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            idempotency_key="ttl-key",
        )
        assert call_counter == 2  # Handler called again after expiry


# ==============================================================================
# Phase 4: End-to-end integration tests
# ==============================================================================


class TestFullFlowIntegration:
    """End-to-end tests covering the full flow described in the
    'How the Layers Work Together' section of the spec."""

    def test_full_flow_sync_with_retry(self, test_domain):
        """API-style flow: process sync with key -> success -> retry with same
        key -> cached result returned -> handler NOT called twice."""
        global call_counter
        identifier = str(uuid4())

        # First call: handler processes command
        result1 = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            idempotency_key="full-sync-1",
        )
        assert call_counter == 1
        assert result1["user_id"] == identifier

        # Retry (e.g., network timeout + client retries)
        result2 = test_domain.process(
            Register(user_id=identifier, email="a@example.com"),
            idempotency_key="full-sync-1",
        )

        # Same result, no extra handler call
        assert result1 == result2
        assert call_counter == 1

        # Command only stored once in event store
        messages = test_domain.event_store.store.read("user:command")
        assert len(messages) == 1

    def test_full_flow_failed_then_retry(self, test_domain):
        """Process sync with key -> handler fails -> retry with same key
        -> handler succeeds -> result cached."""
        test_domain.config["idempotency"]["error_ttl"] = 1
        test_domain._idempotency_store = None

        class UpdateEmail(BaseCommand):
            user_id = Identifier(identifier=True)
            email = String()

        fail_flag = {"should_fail": True}

        class UpdateEmailHandlers(BaseCommandHandler):
            @handle(UpdateEmail)
            def update_email(self, command: UpdateEmail):
                if fail_flag["should_fail"]:
                    fail_flag["should_fail"] = False
                    raise RuntimeError("DB connection lost")
                return {"email": command.email, "status": "updated"}

        test_domain.register(UpdateEmail, part_of=User)
        test_domain.register(UpdateEmailHandlers, part_of=User)
        test_domain.init(traverse=False)

        identifier = str(uuid4())

        # First call fails
        with pytest.raises(RuntimeError, match="DB connection lost"):
            test_domain.process(
                UpdateEmail(user_id=identifier, email="new@example.com"),
                idempotency_key="fail-flow-1",
            )

        # Wait for error TTL
        time.sleep(1.5)

        # Retry succeeds
        result = test_domain.process(
            UpdateEmail(user_id=identifier, email="new@example.com"),
            idempotency_key="fail-flow-1",
        )
        assert result["status"] == "updated"

        # Third call returns cached result
        result2 = test_domain.process(
            UpdateEmail(user_id=identifier, email="new@example.com"),
            idempotency_key="fail-flow-1",
        )
        assert result == result2

    def test_idempotency_key_passed_to_external_service(self, test_domain):
        """Verify handler can access the idempotency key via
        command._metadata.headers.idempotency_key for pass-through
        to external APIs (e.g., Stripe)."""

        class ChargePayment(BaseCommand):
            user_id = Identifier(identifier=True)
            amount = String()

        class ChargePaymentHandlers(BaseCommandHandler):
            @handle(ChargePayment)
            def charge(self, command: ChargePayment):
                # In real code, this would be passed to stripe.PaymentIntent.create(
                #     idempotency_key=key
                # )
                key = command._metadata.headers.idempotency_key
                return {"amount": command.amount, "external_key": key}

        test_domain.register(ChargePayment, part_of=User)
        test_domain.register(ChargePaymentHandlers, part_of=User)
        test_domain.init(traverse=False)

        identifier = str(uuid4())
        result = test_domain.process(
            ChargePayment(user_id=identifier, amount="99.99"),
            idempotency_key="stripe-key-abc123",
        )

        assert result["external_key"] == "stripe-key-abc123"
        assert result["amount"] == "99.99"
