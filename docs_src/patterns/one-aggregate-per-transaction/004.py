from protean import Domain, current_domain, handle
from protean.exceptions import ValidationError
from protean.fields import Boolean, Float, Identifier

domain = Domain(name="OneAggregatePerTransactionEligibility")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)
    is_frozen: Boolean(default=False)
    credit_policy_id: Identifier(required=True)

    def debit(self, amount, transfer_id, target_account_id):
        self.balance -= amount
        self.raise_(
            MoneyDebited(
                account_id=self.account_id,
                amount=amount,
                transfer_id=transfer_id,
                target_account_id=target_account_id,
            )
        )


@domain.event(part_of=Account)
class MoneyDebited:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    transfer_id: Identifier(required=True)
    target_account_id: Identifier(required=True)


@domain.command(part_of=Account)
class TransferMoney:
    transfer_id: Identifier(required=True)
    from_account_id: Identifier(required=True)
    to_account_id: Identifier(required=True)
    amount: Float(required=True)


# --8<-- [start:domain_service]
@domain.aggregate
class CreditPolicy:
    policy_id: Identifier(identifier=True)
    max_transfer_amount: Float(required=True)


@domain.domain_service(part_of=[Account, CreditPolicy])
class TransferEligibilityService:
    """Validates whether a transfer is allowed based on account state
    and credit policies. Does NOT modify any aggregates."""

    @classmethod
    def validate_transfer(cls, source_account, credit_policy, amount):
        if source_account.is_frozen:
            raise ValidationError({"account": ["Source account is frozen"]})

        if amount > credit_policy.max_transfer_amount:
            raise ValidationError(
                {
                    "amount": [
                        f"Transfer exceeds maximum of {credit_policy.max_transfer_amount}"
                    ]
                }
            )

        if source_account.balance - amount < -source_account.overdraft_limit:
            raise ValidationError({"balance": ["Insufficient funds"]})


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(TransferMoney)
    def transfer(self, command: TransferMoney):
        repo = current_domain.repository_for(Account)
        source = repo.get(command.from_account_id)

        policy_repo = current_domain.repository_for(CreditPolicy)
        policy = policy_repo.get(source.credit_policy_id)

        # Domain service validates using both aggregates
        TransferEligibilityService.validate_transfer(
            source,
            policy,
            command.amount,
        )

        # But only the source account is modified
        source.debit(
            command.amount,
            transfer_id=command.transfer_id,
            target_account_id=command.to_account_id,
        )
        repo.add(source)


# --8<-- [end:domain_service]
