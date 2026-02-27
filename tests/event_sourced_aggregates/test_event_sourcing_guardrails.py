"""Tests for Bucket D: Event Sourcing Path guardrails.

Finding #11: from_events() rejects empty event lists.
Finding #12: _apply_handler() raises IncorrectUsageError, not NotImplementedError.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.fields import Identifier, Integer, String


class AccountCreated(BaseEvent):
    account_id: Identifier()
    owner: String()


class FundsDeposited(BaseEvent):
    account_id: Identifier()
    amount: Integer()


class FundsWithdrawn(BaseEvent):
    account_id: Identifier()
    amount: Integer()


class Account(BaseAggregate):
    account_id: Identifier(identifier=True)
    owner: String()
    balance: Integer(default=0)

    @classmethod
    def open(cls, account_id: str, owner: str) -> "Account":
        acct = cls(account_id=account_id, owner=owner)
        acct.raise_(AccountCreated(account_id=account_id, owner=owner))
        return acct

    def deposit(self, amount: int) -> None:
        self.raise_(FundsDeposited(account_id=self.account_id, amount=amount))

    @apply
    def on_created(self, event: AccountCreated) -> None:
        self.account_id = event.account_id
        self.owner = event.owner
        self.balance = 0

    @apply
    def on_deposited(self, event: FundsDeposited) -> None:
        self.balance += event.amount


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account, is_event_sourced=True)
    test_domain.register(AccountCreated, part_of=Account)
    test_domain.register(FundsDeposited, part_of=Account)
    test_domain.register(FundsWithdrawn, part_of=Account)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Finding #11: from_events() rejects empty event lists
# ---------------------------------------------------------------------------
class TestFromEventsEmptyList:
    def test_empty_list_raises_incorrect_usage_error(self):
        """Reconstructing from an empty list is always an error."""
        with pytest.raises(IncorrectUsageError) as exc:
            Account.from_events([])

        assert "empty event list" in exc.value.args[0]
        assert "Account" in exc.value.args[0]

    def test_none_coerced_to_falsy_raises_error(self):
        """Passing None (falsy) also raises the error."""
        with pytest.raises((IncorrectUsageError, TypeError)):
            Account.from_events(None)

    def test_single_event_list_succeeds(self):
        """A list with one event reconstructs normally."""
        uid = str(uuid4())
        events = [AccountCreated(account_id=uid, owner="Alice")]
        acct = Account.from_events(events)

        assert acct.account_id == uid
        assert acct.owner == "Alice"
        assert acct.balance == 0
        assert acct._version == 0

    def test_multiple_events_reconstruct_correctly(self):
        """Multiple events are applied in order."""
        uid = str(uuid4())
        events = [
            AccountCreated(account_id=uid, owner="Bob"),
            FundsDeposited(account_id=uid, amount=100),
            FundsDeposited(account_id=uid, amount=50),
        ]
        acct = Account.from_events(events)

        assert acct.owner == "Bob"
        assert acct.balance == 150
        assert acct._version == 2


# ---------------------------------------------------------------------------
# Finding #12: _apply_handler raises IncorrectUsageError
# ---------------------------------------------------------------------------
class TestApplyHandlerExceptionType:
    def test_missing_handler_raises_incorrect_usage_error(self):
        """A missing @apply handler raises IncorrectUsageError, not NotImplementedError."""
        acct = Account.open(account_id=str(uuid4()), owner="Charlie")

        with pytest.raises(IncorrectUsageError) as exc:
            acct.raise_(FundsWithdrawn(account_id=acct.account_id, amount=10))

        assert "@apply handler" in exc.value.args[0]

    def test_error_message_includes_event_name(self):
        """The error message includes the fully qualified event name."""
        acct = Account.open(account_id=str(uuid4()), owner="Dana")

        with pytest.raises(IncorrectUsageError) as exc:
            acct.raise_(FundsWithdrawn(account_id=acct.account_id, amount=5))

        assert "FundsWithdrawn" in exc.value.args[0]

    def test_error_message_includes_aggregate_name(self):
        """The error message includes the aggregate class name."""
        acct = Account.open(account_id=str(uuid4()), owner="Eve")

        with pytest.raises(IncorrectUsageError) as exc:
            acct.raise_(FundsWithdrawn(account_id=acct.account_id, amount=5))

        assert "Account" in exc.value.args[0]

    def test_handled_event_does_not_raise(self):
        """Events with @apply handlers work normally."""
        acct = Account.open(account_id=str(uuid4()), owner="Frank")
        acct.deposit(200)

        assert acct.balance == 200
