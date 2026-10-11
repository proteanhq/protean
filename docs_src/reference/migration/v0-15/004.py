from protean import Domain, apply
from protean.fields import Float, Identifier

domain = Domain(name="Banking")


# --8<-- [start:events]
@domain.event(part_of="Account")
class AccountOpened:
    account_id = Identifier(required=True)
    balance = Float(required=True)


@domain.event(part_of="Account")
class Withdrawn:
    amount = Float(required=True)


# --8<-- [end:events]


# --8<-- [start:account]
@domain.aggregate(is_event_sourced=True)
class Account:
    balance: Float(default=0.0)

    @classmethod
    def open(cls, balance):
        account = cls._create_new()
        account.raise_(AccountOpened(account_id=account.id, balance=balance))
        return account

    def withdraw(self, amount):
        self.raise_(Withdrawn(amount=amount))  # Only raise the event

    @apply
    def on_opened(self, event: AccountOpened):
        self.id = event.account_id
        self.balance = event.balance

    @apply
    def on_withdrawn(self, event: Withdrawn):
        self.balance -= event.amount  # Runs in live path AND replay


# --8<-- [end:account]
