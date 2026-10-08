from protean import Domain

domain = Domain(name="OneAggregatePerTransactionTransfers")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:transfer]
from protean import current_domain, handle
from protean.exceptions import ValidationError
from protean.fields import Auto, Float, Identifier, List, String


@domain.event(part_of="Account")
class MoneyDebited:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    transfer_id: Identifier(required=True)
    target_account_id: Identifier(required=True)


@domain.command(part_of="Account")
class TransferMoney:
    transfer_id: Identifier(required=True)
    from_account_id: Identifier(required=True)
    to_account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Account:
    account_id: Auto(identifier=True)
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)
    applied_transfer_ids: List(content_type=String)

    def debit(self, amount, transfer_id, target_account_id):
        if self.balance - amount < -self.overdraft_limit:
            raise ValidationError({"balance": ["Insufficient funds for transfer"]})
        self.balance -= amount
        self.raise_(
            MoneyDebited(
                account_id=self.account_id,
                amount=amount,
                transfer_id=transfer_id,
                target_account_id=target_account_id,
            )
        )

    def credit(self, amount, transfer_id):
        self.balance += amount
        self.applied_transfer_ids = [*self.applied_transfer_ids, transfer_id]


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(TransferMoney)
    def transfer(self, command: TransferMoney):
        repo = current_domain.repository_for(Account)
        source = repo.get(command.from_account_id)
        source.debit(
            command.amount,
            transfer_id=command.transfer_id,
            target_account_id=command.to_account_id,
        )
        repo.add(source)
        # Only the source account is modified here.
        # The MoneyDebited event will trigger the credit.


@domain.event_handler(part_of=Account)
class AccountEventHandler:
    @handle(MoneyDebited)
    def on_money_debited(self, event: MoneyDebited):
        repo = current_domain.repository_for(Account)
        target = repo.get(event.target_account_id)
        if event.transfer_id in target.applied_transfer_ids:
            return  # This transfer was already credited
        target.credit(event.amount, transfer_id=event.transfer_id)
        repo.add(target)


# --8<-- [end:transfer]
