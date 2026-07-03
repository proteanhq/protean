"""Reconciliation of the ADR-0015 crash window: events durable in the event
store whose relational outbox row did not land (#1040)."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import Identifier, Integer
from protean.utils.outbox import reconcile_outbox
from tests.shared import MESSAGE_DB_URI


class Account(BaseAggregate):
    balance = Integer(default=0)


class Deposited(BaseEvent):
    account_id = Identifier(required=True)
    amount = Integer(required=True)


def _make_domain(tmp_path, event_store=None):
    db_path = tmp_path / "reconcile.db"
    domain = Domain(name="Reconcile")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{db_path}",
    }
    if event_store is not None:
        domain.config["event_store"] = event_store
    domain.config["enable_outbox"] = True
    domain.config["server"] = {"default_subscription_type": "stream"}
    domain.register(Account)
    domain.register(Deposited, part_of=Account)
    domain.init(traverse=False)
    return domain


def _deposit(domain):
    account = Account(balance=100)
    account.raise_(Deposited(account_id=account.id, amount=100))
    domain.repository_for(Account).add(account)
    return account


def _newest_message_id(domain):
    return domain.event_store.store.read_last_message("$all").metadata.headers.id


@pytest.fixture
def domain_and_repo(tmp_path):
    """A domain with the outbox + aggregate tables created, inside its context."""
    domain = _make_domain(tmp_path)
    with domain.domain_context():
        provider = domain.providers["default"]
        domain.repository_for(Account)._dao  # register aggregate table
        domain._get_outbox_repo("default")._dao  # register outbox table
        provider._metadata.create_all(provider._engine)
        yield domain, domain._get_outbox_repo("default")


@pytest.mark.no_test_domain
class TestOutboxReconciliation:
    def test_reconcile_recreates_a_missing_outbox_row(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        message_id = _newest_message_id(domain)
        assert len(outbox_repo.find_all_by_message_id(message_id)) == 1

        # Simulate the crash window: the event landed in the store but its
        # outbox row did not (here we delete it after the fact).
        outbox_repo._dao._delete_all()
        assert outbox_repo.find_all_by_message_id(message_id) == []

        # Reconcile re-derives the missing row from the event store.
        assert reconcile_outbox(domain) == 1
        rows = outbox_repo.find_all_by_message_id(message_id)
        assert len(rows) == 1
        assert rows[0].target_broker == "default"

    def test_reconcile_is_a_noop_when_nothing_is_missing(self, domain_and_repo):
        domain, _ = domain_and_repo
        _deposit(domain)
        # Fast path: newest event already has its row → no scan, nothing done.
        assert reconcile_outbox(domain) == 0

    def test_reconcile_noop_when_no_events(self, domain_and_repo):
        domain, _ = domain_and_repo
        assert reconcile_outbox(domain) == 0

    def test_reconcile_noop_when_outbox_disabled(self):
        """Without the outbox enabled there is nothing to reconcile — and the
        guard returns before entering a domain context, so no domain is needed.
        """
        domain = Domain(name="NoOutbox")
        domain.init(traverse=False)
        assert reconcile_outbox(domain) == 0

    def test_engine_startup_sweep_repairs_the_crash_window(self, domain_and_repo):
        """The engine's startup sweep recreates a missing outbox row on boot."""
        from protean.server.engine import Engine

        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        message_id = _newest_message_id(domain)

        # Simulate the crash gap: the event is durable, its outbox row is not.
        outbox_repo._dao._delete_all()
        assert outbox_repo.find_all_by_message_id(message_id) == []

        engine = Engine(domain, test_mode=True)
        assert engine._reconcile_outbox_on_startup() == 1
        assert len(outbox_repo.find_all_by_message_id(message_id)) == 1


@pytest.mark.message_db
@pytest.mark.no_test_domain
class TestOutboxReconciliationOnMessageDB:
    """#1073: reconcile_outbox was a permanent no-op on Message-DB because
    ``read_last_message("$all")`` returned None. It must now recover the crash
    window end-to-end against a real Message-DB event store."""

    @pytest.fixture
    def domain_and_repo(self, tmp_path):
        domain = _make_domain(
            tmp_path,
            event_store={"provider": "message_db", "database_uri": MESSAGE_DB_URI},
        )
        with domain.domain_context():
            # Isolate from other Message-DB tests sharing this database: reconcile
            # reads the global "$all" tail, so stray messages would skew it.
            domain.event_store.store._data_reset()
            provider = domain.providers["default"]
            domain.repository_for(Account)._dao
            domain._get_outbox_repo("default")._dao
            provider._metadata.create_all(provider._engine)
            yield domain, domain._get_outbox_repo("default")
            # Leave the shared Message-DB clean for the next test: the "$all"
            # tail read makes this class ordering-sensitive.
            domain.event_store.store._data_reset()

    def test_reconcile_recreates_missing_row_from_message_db(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        # _newest_message_id reads read_last_message("$all") — the fixed path.
        message_id = _newest_message_id(domain)
        assert len(outbox_repo.find_all_by_message_id(message_id)) == 1

        outbox_repo._dao._delete_all()  # simulate the crash window
        assert outbox_repo.find_all_by_message_id(message_id) == []

        # Before the fix this returned 0 (read_last_message("$all") was None).
        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(message_id)) == 1
