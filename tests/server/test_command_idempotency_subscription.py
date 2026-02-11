"""Tests for subscription-level command idempotency dedup (Phase 3).

Verifies that EventStoreSubscription.process_batch() skips messages
that have already been processed (recorded in the idempotency store),
and records success after processing new commands.

All tests require Redis (``--redis`` flag).
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from protean.utils.mixins import handle

REDIS_IDEMPOTENCY_URL = "redis://localhost:6379/5"

pytestmark = pytest.mark.redis


# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------

handler_call_count = 0


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String()


class OpenAccount(BaseCommand):
    account_id = Identifier(identifier=True)
    name = String()


class AccountCommandHandlers(BaseCommandHandler):
    @handle(OpenAccount)
    def open_account(self, command: OpenAccount):
        global handler_call_count
        handler_call_count += 1
        return {"account_id": command.account_id, "count": handler_call_count}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["idempotency"]["redis_url"] = REDIS_IDEMPOTENCY_URL
    test_domain._idempotency_store = None

    # Set command processing to async so process() doesn't call handler
    test_domain.config["command_processing"] = "async"

    test_domain.register(Account)
    test_domain.register(OpenAccount, part_of=Account)
    test_domain.register(AccountCommandHandlers, part_of=Account)
    test_domain.init(traverse=False)

    yield

    test_domain.idempotency_store.flush()


@pytest.fixture(autouse=True)
def reset_counter():
    global handler_call_count
    handler_call_count = 0
    yield


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _submit_and_read_back(test_domain, idempotency_key=None):
    """Submit a command asynchronously and read the message back from the store."""
    identifier = str(uuid4())
    test_domain.process(
        OpenAccount(account_id=identifier, name="Test"),
        asynchronous=True,
        idempotency_key=idempotency_key,
    )
    messages = test_domain.event_store.store.read("account:command")
    # Return the last message (the one we just wrote)
    return messages[-1]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSubscriptionLevelDedup:
    @pytest.mark.asyncio
    async def test_subscription_skips_already_processed_command(self, test_domain):
        """If a command's idempotency key is already recorded as success
        in the store, process_batch should skip it."""
        global handler_call_count

        # Submit a command async with an idempotency key
        message = _submit_and_read_back(test_domain, idempotency_key="sub-skip-1")

        # Pre-seed the idempotency store with a success record
        test_domain.idempotency_store.record_success("sub-skip-1", True)

        # Create engine + subscription
        engine = Engine(domain=test_domain, test_mode=False)
        subscription = EventStoreSubscription(
            engine,
            "account:command",
            AccountCommandHandlers,
            messages_per_tick=10,
        )

        # Process the batch
        result = await subscription.process_batch([message])

        # Handler should NOT have been called — message was skipped
        assert handler_call_count == 0
        assert result == 1  # Still counted as successful (dedup)

    @pytest.mark.asyncio
    async def test_subscription_processes_command_without_idempotency_key(
        self, test_domain
    ):
        """Commands without an idempotency key should be processed normally."""
        global handler_call_count

        message = _submit_and_read_back(test_domain, idempotency_key=None)

        engine = Engine(domain=test_domain, test_mode=False)
        subscription = EventStoreSubscription(
            engine,
            "account:command",
            AccountCommandHandlers,
            messages_per_tick=10,
        )

        result = await subscription.process_batch([message])

        assert handler_call_count == 1
        assert result == 1

    @pytest.mark.asyncio
    async def test_subscription_caches_result_after_async_processing(self, test_domain):
        """After processing a command with an idempotency key,
        the subscription should record success in the idempotency store."""
        message = _submit_and_read_back(test_domain, idempotency_key="sub-cache-1")

        engine = Engine(domain=test_domain, test_mode=False)
        subscription = EventStoreSubscription(
            engine,
            "account:command",
            AccountCommandHandlers,
            messages_per_tick=10,
        )

        await subscription.process_batch([message])

        # Verify the idempotency store was updated
        record = test_domain.idempotency_store.check("sub-cache-1")
        assert record is not None
        assert record["status"] == "success"

    @pytest.mark.asyncio
    async def test_subscription_does_not_cache_without_key(self, test_domain):
        """Commands without an idempotency key should not produce
        entries in the idempotency store."""
        message = _submit_and_read_back(test_domain, idempotency_key=None)

        engine = Engine(domain=test_domain, test_mode=False)
        subscription = EventStoreSubscription(
            engine,
            "account:command",
            AccountCommandHandlers,
            messages_per_tick=10,
        )

        await subscription.process_batch([message])

        # No key → nothing in the store
        # (We can't check by key since there's no key, just verify handler ran)
        assert handler_call_count == 1
