"""
Basic domain service: Fund transfer between two accounts.

This example demonstrates:
- Domain service spanning two Account aggregates
- Pre-invariant: source must have sufficient balance
- Callable pattern: instantiate with aggregates, call to execute
- BaseDomainService.__init__ for invariant support
- Stateless service: mutates aggregates but doesn't persist

Domain: A banking system where transferring funds requires
checking the source balance before debiting. This logic spans
two Account aggregates and doesn't belong to either one.
"""

from protean import Domain, invariant
from protean.core.domain_service import BaseDomainService
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String

domain = Domain(__name__)


# --- Aggregates ---


@domain.aggregate
class Account:
    """Bank account aggregate."""

    account_id: Identifier(identifier=True)
    owner: String(required=True, max_length=100)
    balance: Float(default=0.0)

    def credit(self, amount):
        """Add funds to this account."""
        self.balance += amount

    def debit(self, amount):
        """Remove funds from this account."""
        self.balance -= amount


# --- Domain Service ---


@domain.domain_service(part_of=[Account, Account])
class TransferFunds:
    """Transfer funds between two accounts.

    Validates sufficient balance before transferring.
    The caller (command handler) is responsible for persisting.
    """

    def __init__(self, source, target, amount):
        BaseDomainService.__init__(self, *(source, target))
        self.source = source
        self.target = target
        self.amount = amount

    @invariant.pre
    def source_must_have_sufficient_balance(self):
        """Source account must have enough funds."""
        if self.source.balance < self.amount:
            raise ValidationError({"_service": ["Insufficient balance for transfer"]})

    @invariant.pre
    def amount_must_be_positive(self):
        """Transfer amount must be positive."""
        if self.amount <= 0:
            raise ValidationError({"_service": ["Transfer amount must be positive"]})

    def __call__(self):
        """Execute the transfer: debit source, credit target."""
        self.source.debit(self.amount)
        self.target.credit(self.amount)
