# --8<-- [start:full]
"""Chapter 5: Testing the Ledger

This file contains the domain elements and tests for the Fidelis
banking ledger, demonstrating Protean's event-sourced testing DSL.
"""

import pytest

from protean import Domain, apply, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String
from protean.testing import given
from protean.utils.globals import current_domain

domain = Domain("fidelis")


# --8<-- [start:domain_elements]
@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    account_number: String(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


@domain.event(part_of="Account")
class DepositMade:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.event(part_of="Account")
class WithdrawalMade:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.event(part_of="Account")
class AccountClosed:
    account_id: Identifier(required=True)
    reason: String()


@domain.aggregate(is_event_sourced=True)
class Account:
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")

    @invariant.post
    def balance_must_not_be_negative(self):
        if self.balance is not None and self.balance < 0:
            raise ValidationError(
                {"balance": ["Insufficient funds: balance cannot be negative"]}
            )

    @invariant.post
    def closed_account_must_have_zero_balance(self):
        if self.status == "CLOSED" and self.balance != 0:
            raise ValidationError(
                {"status": ["Cannot close account with non-zero balance"]}
            )

    @classmethod
    def open(cls, account_number: str, holder_name: str, opening_deposit: float):
        account = cls._create_new()
        account.raise_(
            AccountOpened(
                account_id=str(account.id),
                account_number=account_number,
                holder_name=holder_name,
                opening_deposit=opening_deposit,
            )
        )
        return account

    def deposit(self, amount: float, reference: str = None) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Deposit amount must be positive"]})
        self.raise_(
            DepositMade(account_id=str(self.id), amount=amount, reference=reference)
        )

    def withdraw(self, amount: float, reference: str = None) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Withdrawal amount must be positive"]})
        self.raise_(
            WithdrawalMade(account_id=str(self.id), amount=amount, reference=reference)
        )

    def close(self, reason: str = None) -> None:
        self.raise_(AccountClosed(account_id=str(self.id), reason=reason))

    @apply
    def on_account_opened(self, event: AccountOpened):
        self.id = event.account_id
        self.account_number = event.account_number
        self.holder_name = event.holder_name
        self.balance = event.opening_deposit
        self.status = "ACTIVE"

    @apply
    def on_deposit_made(self, event: DepositMade):
        self.balance += event.amount

    @apply
    def on_withdrawal_made(self, event: WithdrawalMade):
        self.balance -= event.amount

    @apply
    def on_account_closed(self, event: AccountClosed):
        self.status = "CLOSED"


@domain.command(part_of=Account)
class OpenAccount:
    account_number: String(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


@domain.command(part_of=Account)
class MakeDeposit:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.command(part_of=Account)
class MakeWithdrawal:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.command(part_of=Account)
class CloseAccount:
    account_id: Identifier(required=True)
    reason: String()


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(OpenAccount)
    def handle_open_account(self, command: OpenAccount):
        account = Account.open(
            account_number=command.account_number,
            holder_name=command.holder_name,
            opening_deposit=command.opening_deposit,
        )
        current_domain.repository_for(Account).add(account)
        return str(account.id)

    @handle(MakeDeposit)
    def handle_make_deposit(self, command: MakeDeposit):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.deposit(command.amount, reference=command.reference)
        repo.add(account)

    @handle(MakeWithdrawal)
    def handle_make_withdrawal(self, command: MakeWithdrawal):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.withdraw(command.amount, reference=command.reference)
        repo.add(account)

    @handle(CloseAccount)
    def handle_close_account(self, command: CloseAccount):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.close(reason=command.reason)
        repo.add(account)


# --8<-- [end:domain_elements]
# --8<-- [start:conftest]
# conftest.py


@pytest.fixture(autouse=True)
def fidelis_domain():
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain


# --8<-- [end:conftest]
# --8<-- [start:fixtures]
@pytest.fixture
def account_opened():
    """Pre-built event representing an opened account."""
    return AccountOpened(
        account_id="acc-123",
        account_number="ACC-001",
        holder_name="Alice Johnson",
        opening_deposit=1000.00,
    )


@pytest.fixture
def funded_account(account_opened):
    """Events representing an account with some transaction history."""
    return [
        account_opened,
        DepositMade(account_id="acc-123", amount=500.00, reference="paycheck"),
        DepositMade(account_id="acc-123", amount=200.00, reference="refund"),
    ]


# --8<-- [end:fixtures]
# --8<-- [start:test_create]


def test_open_account():
    result = given(Account).process(
        OpenAccount(
            account_number="ACC-NEW",
            holder_name="Bob Smith",
            opening_deposit=500.00,
        )
    )

    assert result.accepted
    assert AccountOpened in result.events
    assert result.events[AccountOpened].holder_name == "Bob Smith"
    assert result.holder_name == "Bob Smith"
    assert result.balance == 500.00


# --8<-- [end:test_create]
# --8<-- [start:test_deposit]
def test_deposit_increases_balance(account_opened):
    result = given(Account, account_opened).process(
        MakeDeposit(account_id="acc-123", amount=500.00, reference="paycheck")
    )

    assert result.accepted
    assert DepositMade in result.events
    assert result.events[DepositMade].amount == 500.00
    assert result.balance == 1500.00  # 1000 + 500


# --8<-- [end:test_deposit]
# --8<-- [start:test_rejection]
def test_overdraft_is_rejected(account_opened):
    result = given(Account, account_opened).process(
        MakeWithdrawal(account_id="acc-123", amount=5000.00)
    )

    assert result.rejected
    assert any("Insufficient funds" in m for m in result.rejection_messages)
    assert len(result.events) == 0


# --8<-- [end:test_rejection]
# --8<-- [start:test_lifecycle]
def test_full_account_lifecycle(account_opened):
    result = (
        given(Account, account_opened)
        .process(MakeDeposit(account_id="acc-123", amount=500.00))
        .process(MakeDeposit(account_id="acc-123", amount=200.00))
        .process(MakeWithdrawal(account_id="acc-123", amount=1700.00))
        .process(CloseAccount(account_id="acc-123", reason="Moving abroad"))
    )

    assert result.accepted
    assert result.balance == 0.00
    assert result.status == "CLOSED"
    assert len(result.all_events) == 4  # Deposit + Deposit + Withdrawal + Close


# --8<-- [end:test_lifecycle]
# --8<-- [start:test_close_rejection]
def test_cannot_close_with_balance(account_opened):
    result = given(Account, account_opened).process(
        CloseAccount(account_id="acc-123", reason="Customer request")
    )

    assert result.rejected
    assert any(
        "Cannot close account with non-zero balance" in m
        for m in result.rejection_messages
    )


# --8<-- [end:test_close_rejection]
# --8<-- [end:full]
