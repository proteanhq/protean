"""Chapter 11: Chaining Upcasters

A later schema change adds a ``currency`` field to ``DepositMade``. The
event moves to version 3, and a second upcaster takes v2 payloads to v3.
A stored v1 event passes through both upcasters on replay.
"""

from protean import Domain, apply
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain("fidelis")


@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


# --8<-- [start:deposit_made_v3]
@domain.event(part_of="Account")
class DepositMade:
    __version__ = 3

    account_id: Identifier(required=True)
    amount: Float(required=True)
    source_type: String(default="unknown")
    currency: String(default="USD")  # NEW in v3
    reference: String()


# --8<-- [end:deposit_made_v3]
@domain.aggregate(event_sourced=True)
class Account:
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    currency: String(max_length=3)
    last_source_type: String(max_length=20)

    @classmethod
    def open(cls, holder_name: str, opening_deposit: float):
        account = cls._create_new()
        account.raise_(
            AccountOpened(
                account_id=str(account.id),
                holder_name=holder_name,
                opening_deposit=opening_deposit,
            )
        )
        return account

    def deposit(self, amount: float, source_type: str, currency: str) -> None:
        self.raise_(
            DepositMade(
                account_id=str(self.id),
                amount=amount,
                source_type=source_type,
                currency=currency,
            )
        )

    @apply
    def on_account_opened(self, event: AccountOpened):
        self.id = event.account_id
        self.holder_name = event.holder_name
        self.balance = event.opening_deposit

    @apply
    def on_deposit_made(self, event: DepositMade):
        self.balance += event.amount
        self.currency = event.currency
        self.last_source_type = event.source_type


@domain.upcaster(event_type=DepositMade, from_version=1, to_version=2)
class UpcastDepositV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["source_type"] = "unknown"
        return data


# --8<-- [start:upcaster_v2_to_v3]
@domain.upcaster(event_type=DepositMade, from_version=2, to_version=3)
class UpcastDepositV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


# --8<-- [end:upcaster_v2_to_v3]
domain.init(traverse=False)

if __name__ == "__main__":
    with domain.domain_context():
        repo = current_domain.repository_for(Account)

        account = Account.open(holder_name="Alice Johnson", opening_deposit=1000.00)
        account.deposit(250.00, source_type="bank_transfer", currency="EUR")
        repo.add(account)

        account = repo.get(account.id)
        print(f"Balance: {account.balance:.2f} {account.currency}")
        assert account.currency == "EUR"
        print("All checks passed!")
