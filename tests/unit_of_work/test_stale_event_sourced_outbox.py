"""A stale write on an event-sourced aggregate, with the outbox on, must fail
with ``ExpectedVersionError`` and leave the outbox and the event store as the
winner left them.

Outbox rows carry the event's message id, keyed on the stream and version, so a
stale writer's rows reuse the winner's ids. The commit appends to the event
store before it saves the outbox rows, so the append reports the conflict
first.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.exceptions import ExpectedVersionError, ValidationError
from protean.fields import Identifier, Integer
from tests.shared import MESSAGE_DB_URI, POSTGRES_URI


class Opened(BaseEvent):
    account_id = Identifier(required=True)


class Deposited(BaseEvent):
    account_id = Identifier(required=True)
    amount = Integer(required=True)


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    balance = Integer(default=0)

    @classmethod
    def open(cls, account_id):
        account = cls(account_id=account_id)
        account.raise_(Opened(account_id=account_id))
        return account

    def deposit(self, amount):
        self.raise_(Deposited(account_id=self.account_id, amount=amount))

    @apply
    def opened(self, event: Opened):
        self.account_id = event.account_id
        self.balance = 0

    @apply
    def deposited(self, event: Deposited):
        self.balance += event.amount


def _make_domain(databases=None, event_store=None, external_brokers=None):
    domain = Domain(name="StaleOutbox")
    if databases is not None:
        domain.config["databases"]["default"] = databases
    if event_store is not None:
        domain.config["event_store"] = event_store
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"
    if external_brokers:
        domain.config["outbox"]["external_brokers"] = external_brokers
        for broker in external_brokers:
            domain.config["brokers"][broker] = {"provider": "inline"}
    domain.register(Account, event_sourced=True)
    domain.register(Opened, part_of=Account)
    domain.register(Deposited, part_of=Account, published=True)
    domain.init(traverse=False)
    return domain


@pytest.fixture
def make_domain(request, tmp_path):
    """Yield a factory that builds a domain on the backend named by the param,
    enters its context, and creates the outbox table."""
    backend = request.param
    contexts = []

    def factory(external_brokers=None):
        if backend == "memory":
            domain = _make_domain(external_brokers=external_brokers)
        elif backend == "postgresql":
            domain = _make_domain(
                databases={"provider": "postgresql", "database_uri": POSTGRES_URI},
                event_store={"provider": "message_db", "database_uri": MESSAGE_DB_URI},
                external_brokers=external_brokers,
            )
        else:
            domain = _make_domain(
                databases={
                    "provider": "sqlite",
                    "database_uri": f"sqlite:///{tmp_path / 'stale.db'}",
                },
                event_store={"provider": "message_db", "database_uri": MESSAGE_DB_URI},
                external_brokers=external_brokers,
            )
        ctx = domain.domain_context()
        ctx.push()
        contexts.append((domain, ctx))
        if backend != "memory":
            provider = domain.providers["default"]
            domain._get_outbox_repo("default")._dao  # register the outbox table
            provider._metadata.drop_all(provider._engine)
            provider._metadata.create_all(provider._engine)
        return domain

    yield factory

    for domain, ctx in reversed(contexts):
        if backend != "memory":
            provider = domain.providers["default"]
            provider._metadata.drop_all(provider._engine)
            provider._engine.dispose()
        ctx.pop()


BACKENDS = [
    pytest.param("memory", id="memory"),
    pytest.param(
        "postgresql",
        id="postgresql",
        marks=[pytest.mark.postgresql, pytest.mark.message_db],
    ),
    pytest.param(
        "sqlite",
        id="sqlite",
        marks=[pytest.mark.sqlite, pytest.mark.message_db],
    ),
]


def _outbox_ids(domain):
    rows = domain._get_outbox_repo("default")._dao.query.limit(1000).all().items
    return sorted((row.message_id, row.target_broker) for row in rows)


def _stream(domain, account_id):
    stream = f"{Account.meta_.stream_category}-{account_id}"
    return domain.event_store.store.read(stream)


def _open_and_load_twice(domain):
    """Open an account, commit it, and load two copies of it."""
    account_id = str(uuid4())
    with UnitOfWork():
        domain.repository_for(Account).add(Account.open(account_id))
    repo = domain.repository_for(Account)
    return repo.get(account_id), repo.get(account_id)


def _commit_deposits(domain, account, *amounts):
    with UnitOfWork():
        for amount in amounts:
            account.deposit(amount)
        domain.repository_for(Account).add(account)


@pytest.mark.no_test_domain
@pytest.mark.parametrize("make_domain", BACKENDS, indirect=True)
class TestStaleWriteWithOutbox:
    @pytest.mark.parametrize(
        "external_brokers, stale_amounts",
        [
            pytest.param(None, (5,), id="one-event"),
            pytest.param(None, (5, 6), id="two-events"),
            pytest.param(["ext"], (5,), id="external-broker"),
        ],
    )
    def test_stale_commit_raises_expected_version_error(
        self, make_domain, external_brokers, stale_amounts
    ):
        domain = make_domain(external_brokers=external_brokers)
        winner, loser = _open_and_load_twice(domain)

        _commit_deposits(domain, winner, 10)
        outbox_before = _outbox_ids(domain)
        stream_before = _stream(domain, winner.account_id)
        assert len(stream_before) == 2  # Opened + the winner's Deposited

        with pytest.raises(ExpectedVersionError):
            _commit_deposits(domain, loser, *stale_amounts)

        # The loser added no outbox rows and moved the stream neither in
        # length nor in its last version.
        assert _outbox_ids(domain) == outbox_before
        stream_after = _stream(domain, winner.account_id)
        assert [m.metadata.headers.id for m in stream_after] == [
            m.metadata.headers.id for m in stream_before
        ]
        assert stream_after[-1].metadata.event_store.position == (
            stream_before[-1].metadata.event_store.position
        )

    def test_non_stale_commit_writes_every_row_and_event(self, make_domain):
        domain = make_domain(external_brokers=["ext"])
        account, _ = _open_and_load_twice(domain)
        outbox_before = _outbox_ids(domain)

        _commit_deposits(domain, account, 10, 20)

        stream = _stream(domain, account.account_id)
        assert [m.metadata.headers.type for m in stream] == [
            Opened.__type__,
            Deposited.__type__,
            Deposited.__type__,
        ]
        new_ids = [m.metadata.headers.id for m in stream[1:]]
        # Deposited is published, so each event gets an internal row and one
        # row for the external broker.
        expected = sorted(
            outbox_before
            + [(mid, "default") for mid in new_ids]
            + [(mid, "ext") for mid in new_ids]
        )
        assert _outbox_ids(domain) == expected


@pytest.mark.no_test_domain
def test_bad_partition_key_appends_no_event(tmp_path):
    """A partition key rejected on commit fails before the event-store append."""
    domain = _make_domain()
    with domain.domain_context():
        account_id = str(uuid4())
        with UnitOfWork():
            domain.repository_for(Account).add(Account.open(account_id))
        account = domain.repository_for(Account).get(account_id)
        stream_before = _stream(domain, account_id)
        outbox_before = _outbox_ids(domain)

        # Opt the account category into partition-per-key routing on a field
        # the Deposited event does not carry, so key extraction rejects it.
        domain._partition_keys[Account.meta_.stream_category] = "missing_field"

        with pytest.raises(ValidationError):
            _commit_deposits(domain, account, 10)

        assert len(_stream(domain, account_id)) == len(stream_before)
        assert _outbox_ids(domain) == outbox_before
