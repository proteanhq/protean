# --8<-- [start:full]
from protean import Domain, apply
from protean.fields import Float, Identifier, String

domain = Domain("fidelis")


# --8<-- [start:event]
@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    account_number: String(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


# --8<-- [end:event]
# --8<-- [start:aggregate]
@domain.aggregate(is_event_sourced=True)
class Account:
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")

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

    @apply
    def on_account_opened(self, event: AccountOpened):
        self.id = event.account_id
        self.account_number = event.account_number
        self.holder_name = event.holder_name
        self.balance = event.opening_deposit
        self.status = "ACTIVE"


# --8<-- [end:aggregate]
domain.init(traverse=False)


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Create an account using the factory method
        account = Account.open(
            account_number="ACC-001",
            holder_name="Alice Johnson",
            opening_deposit=1000.00,
        )
        print(f"Created: {account.holder_name} ({account.account_number})")
        print(f"ID: {account.id}")
        print(f"Balance: ${account.balance:.2f}")

        # Persist it — this writes the AccountOpened event to the event store
        repo = domain.repository_for(Account)
        repo.add(account)

        # Retrieve it — this replays events from the event store
        loaded = repo.get(account.id)
        print(f"\nRetrieved: {loaded.holder_name}")
        print(f"Balance: ${loaded.balance:.2f}")
        print(f"Version: {loaded._version}")

        # Verify
        assert loaded.holder_name == "Alice Johnson"
        assert loaded.balance == 1000.00
        assert loaded.status == "ACTIVE"
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
