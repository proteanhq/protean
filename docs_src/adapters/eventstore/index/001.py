# --8<-- [start:full]
# --8<-- [start:write]
from datetime import UTC, datetime

from protean import Domain, apply, handle
from protean.fields import Float, Identifier

domain = Domain(name="Banking")


@domain.event(part_of="Account")
class Opened:
    account_id: Identifier(required=True)


@domain.event(part_of="Account")
class Deposited:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate(event_sourced=True)
class Account:
    balance: Float(default=0.0)

    @classmethod
    def open(cls):
        account = cls._create_new()
        account.raise_(Opened(account_id=account.id))
        return account

    @apply
    def opened(self, event: Opened):
        self.id = event.account_id
        self.balance = 0.0

    @apply
    def deposited(self, event: Deposited):
        self.balance += event.amount

    def deposit(self, amount):
        self.raise_(Deposited(account_id=self.id, amount=amount))


@domain.command(part_of=Account)
class Deposit:
    account_id: Identifier(identifier=True)
    amount: Float(required=True)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(Deposit)
    def deposit(self, command: Deposit):
        repo = domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.deposit(command.amount)
        repo.add(account)


domain.init(traverse=False)

with domain.domain_context():
    account = Account.open()
    account.deposit(100.0)
    account.deposit(50.0)

    # Persisting the aggregate writes its three events to the event store
    domain.repository_for(Account).add(account)
# --8<-- [end:write]

# --8<-- [start:read]
# An aggregate's stream is "<stream category>-<identifier>"
stream = f"{Account.meta_.stream_category}-{account.id}"

with domain.domain_context():
    store = domain.event_store.store

    # Read from the beginning of a stream
    messages = store.read(stream)

    # Read from a specific position
    later = store.read(stream, position=1)

    # Read the last message in a stream
    last = store.read_last_message(stream)
# --8<-- [end:read]

# --8<-- [start:temporal]
with domain.domain_context():
    # Versions count from 0: version 0 is the state after the first event
    opened = domain.event_store.store.load_aggregate(Account, account.id, at_version=0)

    # Load as of a point in time
    current = domain.event_store.store.load_aggregate(
        Account, account.id, as_of=datetime.now(UTC)
    )
# --8<-- [end:temporal]

# --8<-- [start:snapshots]
with domain.domain_context():
    # Create a snapshot for one aggregate
    created = domain.event_store.store.create_snapshot(Account, account.id)

    # Create snapshots for all instances of an aggregate type
    count = domain.event_store.store.create_snapshots(Account)
# --8<-- [end:snapshots]

# --8<-- [start:causation]
with domain.domain_context():
    domain.process(Deposit(account_id=account.id, amount=25.0), asynchronous=False)
    event = domain.event_store.store.read_last_message(stream)

    # Walk up from an event to the command that caused it
    chain = domain.event_store.store.trace_causation(event.metadata.headers.id)

    # Find everything the command caused
    effects = domain.event_store.store.trace_effects(chain[0].metadata.headers.id)

    # Build the full tree for the event's correlation id
    tree = domain.event_store.store.build_causation_tree(
        event.metadata.domain.correlation_id
    )
# --8<-- [end:causation]
# --8<-- [end:full]
