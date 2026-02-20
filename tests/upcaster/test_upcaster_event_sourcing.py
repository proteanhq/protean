"""Tests for upcasting during event-sourced aggregate reconstruction."""

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String


# ── Domain elements ──────────────────────────────────────────────────────


class AccountOpened(BaseEvent):
    """Current version — v2 added the currency field."""

    __version__ = "v2"
    account_id = Identifier(required=True)
    owner = String(required=True)
    initial_balance = Float(required=True)
    currency = String(required=True)


class AccountCredited(BaseEvent):
    """Unchanged event — still v1."""

    __version__ = "v1"
    account_id = Identifier(required=True)
    amount = Float(required=True)


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    owner = String()
    balance = Float(default=0.0)
    currency = String(default="USD")

    @apply
    def on_opened(self, event: AccountOpened) -> None:
        self.account_id = event.account_id
        self.owner = event.owner
        self.balance = event.initial_balance
        self.currency = event.currency

    @apply
    def on_credited(self, event: AccountCredited) -> None:
        self.balance += event.amount


# ── Upcasters ────────────────────────────────────────────────────────────


class UpcastAccountOpenedV1ToV2(BaseUpcaster):
    """v1 had no currency field — default to USD."""

    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account, is_event_sourced=True)
    test_domain.register(AccountOpened, part_of=Account)
    test_domain.register(AccountCredited, part_of=Account)
    test_domain.upcaster(
        UpcastAccountOpenedV1ToV2,
        event_type=AccountOpened,
        from_version="v1",
        to_version="v2",
    )
    test_domain.init(traverse=False)


def _write_raw_event(
    store,
    stream: str,
    type_string: str,
    version: str,
    data: dict,
    position: int,
) -> None:
    """Write a raw event dict directly to the event store (positional args)."""
    store._write(
        stream,
        type_string,
        data,
        {
            "headers": {
                "id": f"evt-{position}",
                "type": type_string,
                "time": "2025-01-01T00:00:00+00:00",
                "stream": stream,
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": f"tests.upcaster.test_upcaster_event_sourcing.{type_string.split('.')[1]}",
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": stream.rsplit("-", 1)[0],
                "version": version,
                "sequence_id": str(position),
                "asynchronous": True,
            },
        },
        position - 1,
    )


# ── Tests ────────────────────────────────────────────────────────────────


class TestAggregateReconstructionWithMixedVersions:
    """Simulate an aggregate whose events span multiple schema versions."""

    def test_load_aggregate_with_v1_creation_event(self, test_domain):
        store = test_domain.event_store.store
        stream = "test::account-acct-1"

        # Write a v1 AccountOpened (no currency field)
        _write_raw_event(
            store,
            stream,
            "Test.AccountOpened.v1",
            "v1",
            {"account_id": "acct-1", "owner": "Alice", "initial_balance": 100.0},
            position=0,
        )

        # Write a v1 AccountCredited (unchanged schema)
        _write_raw_event(
            store,
            stream,
            "Test.AccountCredited.v1",
            "v1",
            {"account_id": "acct-1", "amount": 50.0},
            position=1,
        )

        # Load aggregate — v1 AccountOpened should be upcast to v2
        aggregate = store.load_aggregate(Account, "acct-1")

        assert aggregate is not None
        assert aggregate.account_id == "acct-1"
        assert aggregate.owner == "Alice"
        assert aggregate.balance == 150.0  # 100 + 50
        assert aggregate.currency == "USD"  # Default from upcaster

    def test_load_aggregate_with_current_version_events(self, test_domain):
        store = test_domain.event_store.store
        stream = "test::account-acct-2"

        # Write a v2 AccountOpened (current version, has currency)
        _write_raw_event(
            store,
            stream,
            "Test.AccountOpened.v2",
            "v2",
            {
                "account_id": "acct-2",
                "owner": "Bob",
                "initial_balance": 200.0,
                "currency": "EUR",
            },
            position=0,
        )

        aggregate = store.load_aggregate(Account, "acct-2")

        assert aggregate is not None
        assert aggregate.owner == "Bob"
        assert aggregate.balance == 200.0
        assert aggregate.currency == "EUR"

    def test_apply_handler_receives_upcast_event(self, test_domain):
        store = test_domain.event_store.store
        stream = "test::account-acct-3"

        # Write a v1 event
        _write_raw_event(
            store,
            stream,
            "Test.AccountOpened.v1",
            "v1",
            {"account_id": "acct-3", "owner": "Charlie", "initial_balance": 0.0},
            position=0,
        )

        aggregate = store.load_aggregate(Account, "acct-3")

        # The @apply handler received the upcast event with currency="USD"
        assert aggregate.currency == "USD"
        assert aggregate.owner == "Charlie"


class TestRepositoryWithUpcasting:
    """Test that repository.get() works with old-version events."""

    def test_repository_get_with_old_events(self, test_domain):
        store = test_domain.event_store.store
        stream = "test::account-acct-repo"

        _write_raw_event(
            store,
            stream,
            "Test.AccountOpened.v1",
            "v1",
            {"account_id": "acct-repo", "owner": "Diana", "initial_balance": 500.0},
            position=0,
        )
        _write_raw_event(
            store,
            stream,
            "Test.AccountCredited.v1",
            "v1",
            {"account_id": "acct-repo", "amount": 25.0},
            position=1,
        )

        repo = test_domain.repository_for(Account)
        account = repo.get("acct-repo")

        assert account.owner == "Diana"
        assert account.balance == 525.0
        assert account.currency == "USD"
