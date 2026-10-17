# --8<-- [start:transfer]
from protean import Domain, handle
from protean.fields import Float, Identifier, List, String
from protean.utils.globals import current_domain

domain = Domain(name="Transfers")


@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    balance: Float(default=0.0)
    credited_transfers: List(content_type=String)

    def debit(self, amount: float, transfer_id: str, to_account: str) -> None:
        self.balance -= amount
        self.raise_(
            MoneyDebited(
                transfer_id=transfer_id,
                from_account=self.account_id,
                to_account=to_account,
                amount=amount,
            )
        )

    def credit(self, amount: float, transfer_id: str) -> None:
        # The target account remembers which transfers it has received,
        # so a redelivered MoneyDebited event credits it only once.
        if transfer_id in self.credited_transfers:
            return
        self.balance += amount
        self.credited_transfers.append(transfer_id)


@domain.event(part_of=Account)
class MoneyDebited:
    transfer_id: Identifier(required=True)
    from_account: Identifier(required=True)
    to_account: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of=Account)
class TransferMoney:
    transfer_id: Identifier(identifier=True)
    from_account: String(required=True)
    to_account: String(required=True)
    amount: Float(required=True)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(TransferMoney)
    def transfer(self, command: TransferMoney) -> None:
        repo = current_domain.repository_for(Account)
        source = repo.get(command.from_account)

        # Only the source account is modified by the command handler
        source.debit(
            command.amount,
            transfer_id=command.transfer_id,
            to_account=command.to_account,
        )
        repo.add(source)

        # The MoneyDebited event triggers an event handler that credits
        # the target account in its own transaction.


@domain.event_handler(part_of=Account)
class CreditTargetAccount:
    @handle(MoneyDebited)
    def credit_target(self, event: MoneyDebited) -> None:
        repo = current_domain.repository_for(Account)
        target = repo.get(event.to_account)
        target.credit(event.amount, transfer_id=event.transfer_id)
        repo.add(target)


# --8<-- [end:transfer]
