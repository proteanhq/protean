"""
Basic domain service: Fund transfer between two accounts.

This example demonstrates:
- Domain service spanning two Account aggregates
- Pre-invariants: the amount is positive, the source has enough funds, and
  the source and target are different accounts
- Callable pattern: instantiate with aggregates, call to execute
- The service validates both accounts but changes only the source account
- One aggregate per transaction: the command handler persists only the source
- The destination is credited through an event and a command
- Each account records the transfer ids it has applied, so a repeated debit or
  credit for the same transfer changes nothing

Domain: A banking system where transferring funds requires checking the
source balance before debiting. The rule spans two Account aggregates and
belongs to neither one.

The check across both accounts happens in one step, in the source account's
transaction. The credit to the destination happens later, in its own
transaction, so the destination's balance is eventually consistent.

Processing is synchronous, so one TransferFunds command runs the debit and the
credit in-process, with no broker and no server. A deployed domain leaves both
asynchronous and lets the server deliver the event and the command.

Usage:
    from domain_service_flow_basic import Account, TransferFunds, domain

    domain.init(traverse=False)
    with domain.domain_context():
        repo = domain.repository_for(Account)
        repo.add(Account(account_id="A-1", owner="Ann", balance=100.0))
        repo.add(Account(account_id="B-1", owner="Bob", balance=0.0))

        domain.process(
            TransferFunds(
                transfer_id="T-1",
                source_id="A-1",
                target_id="B-1",
                amount=40.0,
            )
        )
        # A-1 now holds 60.0 and B-1 holds 40.0.
"""

from protean import Domain, current_domain, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, List, String

domain = Domain(__name__)

# Run the whole transfer in-process: FundsDebited reaches the event handler when
# the unit of work that saves the source account commits, and CreditAccount
# reaches its handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --- Commands ---


@domain.command(part_of="Account")
class TransferFunds:
    """Move money from one account to another.

    The caller supplies `transfer_id`. The source account records it with the
    debit, and the event and the credit command carry it to the destination.
    A repeated TransferFunds, or one that reuses the id with another amount,
    then moves no money. Each account sees only its own list, so the caller
    must give every transfer its own id: an id reused from another source
    account is debited and then skipped at the destination.
    """

    transfer_id: Identifier(required=True)
    source_id: Identifier(required=True)
    target_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of="Account")
class CreditAccount:
    """Credit one account with the money from one transfer."""

    transfer_id: Identifier(required=True)
    account_id: Identifier(required=True)
    amount: Float(required=True)


# --- Events ---


@domain.event(part_of="Account")
class FundsDebited:
    """Raised when the source account is debited for a transfer."""

    transfer_id: Identifier(required=True)
    source_id: Identifier(required=True)
    target_id: Identifier(required=True)
    amount: Float(required=True)


# --- Aggregates ---


@domain.aggregate
class Account:
    """Bank account aggregate.

    `applied_transfer_ids` records the transfers already debited from or
    credited to this account. A transfer touches each account once, so one
    list serves both sides, and a repeated command for the same transfer
    changes nothing. The list grows with every transfer and loads with the
    account each time.
    """

    account_id: Identifier(identifier=True)
    owner: String(required=True, max_length=100)
    balance: Float(default=0.0)
    applied_transfer_ids: List(content_type=String)

    def debit_for_transfer(self, transfer_id, target_id, amount):
        """Remove funds for a transfer, record it, and announce it."""
        self.balance -= amount
        self.applied_transfer_ids = [*self.applied_transfer_ids, transfer_id]
        self.raise_(
            FundsDebited(
                transfer_id=transfer_id,
                source_id=self.account_id,
                target_id=target_id,
                amount=amount,
            )
        )

    def credit_for_transfer(self, transfer_id, amount):
        """Add funds for a transfer and record that it was applied."""
        self.balance += amount
        self.applied_transfer_ids = [*self.applied_transfer_ids, transfer_id]


# --- Domain Service ---


@domain.domain_service(part_of=[Account, Account])
class FundsTransferService:
    """Check a transfer against both accounts and debit the source.

    The service reads both accounts but changes only the source. The caller
    (command handler) persists the source; the destination is credited later.
    """

    def __init__(self, source, target, transfer_id, amount):
        self.source = source
        self.target = target
        self.transfer_id = transfer_id
        self.amount = amount

    @invariant.pre
    def amount_must_be_positive(self):
        """Transfer amount must be positive."""
        if self.amount <= 0:
            raise ValidationError({"_service": ["Transfer amount must be positive"]})

    @invariant.pre
    def source_must_have_sufficient_balance(self):
        """Source account must have enough funds."""
        if self.source.balance < self.amount:
            raise ValidationError({"_service": ["Insufficient balance for transfer"]})

    @invariant.pre
    def accounts_must_differ(self):
        """A transfer needs two different accounts."""
        if self.source.account_id == self.target.account_id:
            raise ValidationError(
                {"_service": ["Source and target must be different accounts"]}
            )

    def __call__(self):
        """Debit the source. The destination is credited through FundsDebited."""
        self.source.debit_for_transfer(
            self.transfer_id, self.target.account_id, self.amount
        )


# --- Command Handler (the write path for Account) ---


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    """Each handler method persists one Account."""

    @handle(TransferFunds)
    def transfer(self, command: TransferFunds):
        """Validate across both accounts, then persist only the source."""
        repo = current_domain.repository_for(Account)
        source = repo.get(command.source_id)
        if command.transfer_id in source.applied_transfer_ids:
            # Already debited. Debiting again would take the money twice, even
            # when the repeat carries a different amount.
            return
        target = repo.get(command.target_id)

        FundsTransferService(source, target, command.transfer_id, command.amount)()

        repo.add(source)

    @handle(CreditAccount)
    def credit(self, command: CreditAccount):
        """Credit the destination once per transfer."""
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        if command.transfer_id in account.applied_transfer_ids:
            # Already applied. A redelivered FundsDebited reissues CreditAccount,
            # and crediting again would pay the transfer twice.
            return
        account.credit_for_transfer(command.transfer_id, command.amount)
        repo.add(account)


# --- The cross-aggregate link: an event handler in Account's cluster ---


@domain.event_handler(part_of=Account)
class CreditTransferTarget:
    """React to FundsDebited and ask the destination account for the credit.

    The handler sits in Account's cluster, which owns FundsDebited. It does not
    write the destination itself; it issues CreditAccount, and the Account
    command handler does the write in a transaction separate from the debit.
    With sync command processing, as in this file, that write joins this
    handler's transaction.
    """

    @handle(FundsDebited)
    def on_funds_debited(self, event: FundsDebited):
        current_domain.process(
            CreditAccount(
                transfer_id=event.transfer_id,
                account_id=event.target_id,
                amount=event.amount,
            )
        )
