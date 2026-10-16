# --8<-- [start:transfer]
from protean import Domain, current_domain, handle
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import ValidationError
from protean.fields import Auto, Float, Identifier

domain = Domain(name="ThinHandlersTransfers")


@domain.event(part_of="Account")
class MoneyDebited:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    transfer_id: Identifier(required=True)
    target_account_id: Identifier(required=True)


@domain.aggregate
class Account:
    account_id: Auto(identifier=True)
    balance: Float(default=0.0)
    risk_score: Float(default=0.0)
    credit_policy_id: Identifier(required=True)

    def debit(self, amount: float, transfer_id: str, target_account_id: str) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Transfer amount must be positive"]})

        if amount > self.balance:
            raise ValidationError({"balance": ["Insufficient funds"]})

        self.balance -= amount
        self.raise_(
            MoneyDebited(
                account_id=self.account_id,
                amount=amount,
                transfer_id=transfer_id,
                target_account_id=target_account_id,
            )
        )


@domain.aggregate
class CreditPolicy:
    policy_id: Auto(identifier=True)
    max_transfer_amount: Float(required=True)
    max_risk_score: Float(required=True)


@domain.command(part_of=Account)
class TransferMoney:
    transfer_id: Identifier(required=True)
    from_account_id: Identifier(required=True)
    to_account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.domain_service(part_of=[Account, CreditPolicy])
class TransferService:
    """Validates transfer eligibility across Account and CreditPolicy."""

    def __init__(self, source: Account, policy: CreditPolicy):
        super().__init__(source, policy)

        self.source = source
        self.policy = policy

    def validate_and_debit(
        self, amount: float, transfer_id: str, target_account_id: str
    ) -> None:
        """Validate the transfer and debit the source account."""
        if amount > self.policy.max_transfer_amount:
            raise ValidationError(
                {
                    "amount": [
                        f"Exceeds policy limit of {self.policy.max_transfer_amount}"
                    ]
                }
            )

        if self.source.risk_score > self.policy.max_risk_score:
            raise ValidationError(
                {"risk": ["Account risk score exceeds policy threshold"]}
            )

        # Delegate the actual debit to the aggregate
        self.source.debit(amount, transfer_id, target_account_id)


# --8<-- [end:transfer]


# --8<-- [start:handler]
@domain.command_handler(part_of=Account)
class AccountCommandHandler(BaseCommandHandler):
    @handle(TransferMoney)
    def transfer(self, command: TransferMoney):
        account_repo = current_domain.repository_for(Account)
        policy_repo = current_domain.repository_for(CreditPolicy)

        source = account_repo.get(command.from_account_id)
        # A second aggregate, loaded for the domain service
        policy = policy_repo.get(source.credit_policy_id)

        TransferService(source, policy).validate_and_debit(
            amount=command.amount,
            transfer_id=command.transfer_id,
            target_account_id=command.to_account_id,
        )

        account_repo.add(source)


# --8<-- [end:handler]
