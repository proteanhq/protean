# --8<-- [start:datetime_import]
from datetime import UTC, datetime

# --8<-- [end:datetime_import]
from protean import Domain, apply
from protean.fields import Float, Identifier

domain = Domain(name="myapp")


# --8<-- [start:account]
@domain.event(part_of="Account")
class AccountOpened:
    account_id = Identifier(required=True)


@domain.event(part_of="Account")
class Deposited:
    amount = Float(required=True)


@domain.aggregate(event_sourced=True)
class Account:
    balance = Float(default=0.0)

    @classmethod
    def open(cls, account_id):
        account = cls(id=account_id)
        account.raise_(AccountOpened(account_id=account_id))
        return account

    def deposit(self, amount):
        self.raise_(Deposited(amount=amount))

    # The first event sets every field: replay starts from a blank aggregate
    @apply
    def on_opened(self, event: AccountOpened):
        self.id = event.account_id
        self.balance = 0.0

    @apply
    def on_deposited(self, event: Deposited):
        self.balance += event.amount


# --8<-- [end:account]


# --8<-- [start:read]
def read_account_events():
    store = domain.event_store.store

    # Read from beginning of stream
    messages = store.read("myapp::account-acc-001")

    # Read from a specific position
    later = store.read("myapp::account-acc-001", position=5)

    # Read last message
    last = store.read_last_message("myapp::account-acc-001")

    # Page through a whole stream without a size cap. `read_all` is a generator
    # that reads in `page_size` batches until the stream is exhausted, so it is
    # safe to iterate a store larger than a single `read` returns.
    deposited = 0.0
    for message in store.read_all("myapp::account", page_size=1000):
        deposited += message.data.get("amount", 0.0)  # handle each message

    return messages, later, last, deposited


# --8<-- [end:read]


# --8<-- [start:temporal]
def account_history(account_id):
    repo = domain.repository_for(Account)

    # Load at a specific version
    at_version = repo.get(account_id, at_version=5)

    # Load state as of a point in time
    as_of = repo.get(account_id, as_of=datetime(2024, 6, 15, 12, 0, tzinfo=UTC))

    return at_version, as_of


# --8<-- [end:temporal]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        account = Account.open("acc-001")
        for amount in (10.0, 20.0, 30.0, 40.0, 50.0, 60.0):
            account.deposit(amount)
        domain.repository_for(Account).add(account)

        messages, later, last, deposited = read_account_events()
        print(len(messages), last.data, deposited)
