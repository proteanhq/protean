# --8<-- [start:account]
from datetime import date

from protean import Domain, current_domain, handle
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import ValidationError
from protean.fields import Auto, Date, Float, Identifier, String

domain = Domain(name="ThinHandlersAccounts")


@domain.event(part_of="Account")
class MoneyWithdrawn:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    new_balance: Float(required=True)


@domain.command(part_of="Account")
class WithdrawMoney:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Account:
    account_id: Auto(identifier=True)
    balance: Float(default=0.0)
    overdraft_limit: Float(default=0.0)
    status: String(default="active")
    daily_withdrawal_total: Float(default=0.0)
    last_withdrawal_date: Date()

    DAILY_WITHDRAWAL_LIMIT = 5000.0

    def withdraw(self, amount: float) -> None:
        """Withdraw money from this account."""
        if self.status != "active":
            raise ValidationError(
                {"status": ["Cannot withdraw from a non-active account"]}
            )

        if amount <= 0:
            raise ValidationError({"amount": ["Withdrawal amount must be positive"]})

        self._check_daily_limit(amount)

        if self.balance - amount < -self.overdraft_limit:
            raise ValidationError({"balance": ["Insufficient funds"]})

        self.balance -= amount
        self._update_daily_total(amount)

        self.raise_(
            MoneyWithdrawn(
                account_id=self.account_id,
                amount=amount,
                new_balance=self.balance,
            )
        )

    def _check_daily_limit(self, amount: float) -> None:
        today = date.today()
        if self.last_withdrawal_date != today:
            self.daily_withdrawal_total = 0.0

        if self.daily_withdrawal_total + amount > self.DAILY_WITHDRAWAL_LIMIT:
            raise ValidationError(
                {
                    "amount": [
                        f"Daily withdrawal limit of {self.DAILY_WITHDRAWAL_LIMIT} exceeded"
                    ]
                }
            )

    def _update_daily_total(self, amount: float) -> None:
        today = date.today()
        if self.last_withdrawal_date != today:
            self.daily_withdrawal_total = amount
        else:
            self.daily_withdrawal_total += amount
        self.last_withdrawal_date = today


# --8<-- [end:account]


@domain.command_handler(part_of=Account)
class AccountCommandHandler(BaseCommandHandler):
    @handle(WithdrawMoney)
    def withdraw(self, command: WithdrawMoney):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.withdraw(command.amount)
        repo.add(account)
