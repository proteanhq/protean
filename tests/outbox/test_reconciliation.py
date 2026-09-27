"""Reconciliation of the ADR-0015 crash window: events durable in the event
store whose relational outbox row did not land."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.domain import Domain
from protean.fields import Identifier, Integer
from protean.utils.eventing import Message, MessageHeaders, Metadata
from protean.utils.mixins import handle
from protean.utils.outbox import _is_outboxed_event, reconcile_outbox
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

    def test_reconcile_scans_from_tail_minus_limit_plus_one(
        self, domain_and_repo, monkeypatch
    ):
        """The tail scan starts at ``max(0, tail - limit + 1)``.

        With more events than ``limit``, reconcile must scan only the newest
        ``limit`` events — the window ending at the tail. This pins the
        off-by-one arithmetic: any drift in ``tail - limit + 1`` reads the wrong
        slice and silently fails to repair the crash-window event.
        """
        domain, outbox_repo = domain_and_repo
        for _ in range(4):
            _deposit(domain)
        store = domain.event_store.store
        tail = store.read_last_message("$all").metadata.event_store.global_position

        outbox_repo._dao._delete_all()  # crash window: newest row missing → scan

        positions = []
        real_read = store.read

        def spy(*args, **kwargs):
            positions.append(kwargs.get("position"))
            return real_read(*args, **kwargs)

        monkeypatch.setattr(store, "read", spy)

        limit = 2
        reconcile_outbox(domain, limit=limit)

        assert positions == [max(0, tail - limit + 1)]
        assert tail - limit + 1 > 0  # guard: we're testing the un-clamped path

    def test_reconcile_clamps_scan_start_to_zero(self, domain_and_repo, monkeypatch):
        """When there are fewer events than ``limit``, the scan starts at 0.

        ``max(0, tail - limit + 1)`` must clamp a negative start to 0 rather than
        reading from a positive offset that would skip the earliest events.
        """
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        _deposit(domain)
        store = domain.event_store.store

        outbox_repo._dao._delete_all()

        positions = []
        real_read = store.read

        def spy(*args, **kwargs):
            positions.append(kwargs.get("position"))
            return real_read(*args, **kwargs)

        monkeypatch.setattr(store, "read", spy)

        reconcile_outbox(domain, limit=1000)  # limit >> number of events

        assert positions == [0]

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
    """reconcile_outbox was a permanent no-op on Message-DB because
    ``read_last_message("$all")`` returned None. It must now recover the crash
    window end-to-end against a real Message-DB event store."""

    @pytest.fixture
    def domain_and_repo(self, tmp_path):
        # The autouse ``_isolate_message_db`` fixture (keyed on the ``message_db``
        # marker) gives this test a clean store, so the "$all" tail read below
        # sees only this test's writes. ``no_test_domain`` skips the store
        # cleanup in ``run_around_tests``, so close the store here to avoid a
        # connection-pool leak.
        domain = _make_domain(
            tmp_path,
            event_store={"provider": "message_db", "database_uri": MESSAGE_DB_URI},
        )
        with domain.domain_context():
            provider = domain.providers["default"]
            domain.repository_for(Account)._dao
            domain._get_outbox_repo("default")._dao
            provider._metadata.create_all(provider._engine)
            yield domain, domain._get_outbox_repo("default")
            domain.event_store.store.close()

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


# --- Ownership filter (#1648) ------------------------------------------------
#
# Only events raised by this domain's aggregates get outbox rows from the unit
# of work, so only those may be repaired. Foreign events in a shared store,
# commands, and process manager transitions must be skipped, both in the
# fast-path check and in the repair set.


class Deposit(BaseCommand):
    account_id = Identifier(required=True)
    amount = Integer(required=True)


class AccountCommandHandler(BaseCommandHandler):
    @handle(Deposit)
    def deposit(self, command):
        pass


class DepositTrackerPM(BaseProcessManager):
    account_id = Identifier()

    @handle(Deposited, start=True, correlate="account_id")
    def on_deposited(self, event):
        self.account_id = event.account_id


class SequencedDepositHandler(BaseEventHandler):
    @handle(Deposited)
    def on_deposited(self, event):
        pass


class Shipment(BaseAggregate):
    status = Integer(default=0)


class Shipped(BaseEvent):
    shipment_id = Identifier(required=True)


def _make_foreign_domain(**config):
    """A second domain, named differently, whose events stand in for another
    bounded context writing to a shared event store."""
    domain = Domain(name="Other", config=config or None)
    domain.register(Shipment)
    domain.register(Shipped, part_of=Shipment)
    domain.init(traverse=False)
    return domain


def _append_foreign_event(domain, foreign_domain):
    """Append another domain's event to *domain*'s event store and return its
    message id. The message carries the foreign type string
    (``Other.Shipped.v1``), exactly as a shared store would hold it."""
    with foreign_domain.domain_context():
        shipment = Shipment()
        shipment.raise_(Shipped(shipment_id=shipment.id))
        message = Message.from_domain_object(shipment._events[-1])
    domain.event_store.store._write(
        message.metadata.headers.stream,
        message.metadata.headers.type,
        message.data,
        metadata=message.metadata.to_dict(),
    )
    return message.metadata.headers.id


def _deposited_message_ids(domain):
    return [
        m.metadata.headers.id
        for m in domain.event_store.store.read("$all")
        if m.metadata.headers.type == Deposited.__type__
    ]


def _make_domain_with(tmp_path, *elements):
    """Like ``_make_domain`` but registers extra ``(cls, kwargs)`` elements
    before ``init``, and creates the tables inside the domain context."""
    db_path = tmp_path / "reconcile.db"
    domain = Domain(name="Reconcile")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{db_path}",
    }
    domain.config["enable_outbox"] = True
    domain.config["server"] = {"default_subscription_type": "stream"}
    domain.register(Account)
    domain.register(Deposited, part_of=Account)
    for cls, kwargs in elements:
        domain.register(cls, **kwargs)
    domain.init(traverse=False)
    return domain


@pytest.fixture
def foreign_domain():
    return _make_foreign_domain()


def _create_tables(domain):
    provider = domain.providers["default"]
    domain.repository_for(Account)._dao
    domain._get_outbox_repo("default")._dao
    provider._metadata.create_all(provider._engine)
    return domain._get_outbox_repo("default")


@pytest.mark.no_test_domain
class TestReconcileSkipsForeignEvents:
    def test_foreign_event_at_tail_with_nothing_missing_is_a_noop(
        self, domain_and_repo, foreign_domain
    ):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        foreign_id = _append_foreign_event(domain, foreign_domain)
        assert _newest_message_id(domain) == foreign_id  # precondition

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(foreign_id) == []

    def test_lost_row_behind_a_foreign_tail_is_repaired_alone(
        self, domain_and_repo, foreign_domain
    ):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        [own_id] = _deposited_message_ids(domain)
        outbox_repo._dao._delete_all()
        foreign_id = _append_foreign_event(domain, foreign_domain)

        assert reconcile_outbox(domain) == 1
        rows = outbox_repo.find_all_by_message_id(own_id)
        assert len(rows) == 1
        assert rows[0].type == Deposited.__type__
        assert outbox_repo.find_all_by_message_id(foreign_id) == []

    def test_window_with_only_foreign_messages_creates_nothing(
        self, domain_and_repo, foreign_domain
    ):
        domain, outbox_repo = domain_and_repo
        foreign_ids = [_append_foreign_event(domain, foreign_domain) for _ in range(2)]

        assert reconcile_outbox(domain) == 0
        for foreign_id in foreign_ids:
            assert outbox_repo.find_all_by_message_id(foreign_id) == []

    def test_limit_counts_foreign_messages_in_the_window(
        self, domain_and_repo, foreign_domain
    ):
        """``limit`` is the number of ``$all`` messages scanned, foreign ones
        included, so a lost row pushed out by newer foreign messages is not
        reached until the window widens."""
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        [own_id] = _deposited_message_ids(domain)
        outbox_repo._dao._delete_all()
        for _ in range(3):
            _append_foreign_event(domain, foreign_domain)

        assert reconcile_outbox(domain, limit=3) == 0
        assert outbox_repo.find_all_by_message_id(own_id) == []

        assert reconcile_outbox(domain, limit=4) == 1
        assert len(outbox_repo.find_all_by_message_id(own_id)) == 1

    def test_engine_startup_sweep_repairs_behind_a_foreign_tail(
        self, domain_and_repo, foreign_domain
    ):
        from protean.server.engine import Engine

        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        [own_id] = _deposited_message_ids(domain)
        outbox_repo._dao._delete_all()
        foreign_id = _append_foreign_event(domain, foreign_domain)

        engine = Engine(domain, test_mode=True)
        assert engine._reconcile_outbox_on_startup() == 1
        assert len(outbox_repo.find_all_by_message_id(own_id)) == 1
        assert outbox_repo.find_all_by_message_id(foreign_id) == []


@pytest.mark.no_test_domain
class TestReconcileSkipsCommands:
    @pytest.fixture
    def domain_and_repo(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (Deposit, {"part_of": Account}),
            (AccountCommandHandler, {"part_of": Account}),
        )
        with domain.domain_context():
            yield domain, _create_tables(domain)

    def _process_deposit(self, domain):
        command = Deposit(account_id="acc-1", amount=10)
        domain.process(command, asynchronous=True)
        [command_id] = [
            m.metadata.headers.id
            for m in domain.event_store.store.read("$all")
            if m.metadata.headers.type == Deposit.__type__
        ]
        assert _newest_message_id(domain) == command_id  # precondition
        return command_id

    def test_command_as_last_write_is_a_noop(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        command_id = self._process_deposit(domain)

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(command_id) == []

    def test_command_as_last_write_does_not_hide_a_lost_event_row(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        [event_id] = _deposited_message_ids(domain)
        outbox_repo._dao._delete_all()
        command_id = self._process_deposit(domain)

        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(event_id)) == 1
        assert outbox_repo.find_all_by_message_id(command_id) == []


@pytest.mark.no_test_domain
class TestReconcileSkipsProcessManagerTransitions:
    @pytest.fixture
    def domain_and_repo(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (DepositTrackerPM, {"stream_categories": ["reconcile::account"]}),
        )
        with domain.domain_context():
            yield domain, _create_tables(domain)

    def _transition_id(self, domain):
        """Return the id of the transition event the process manager appended
        when it handled the deposit (the test domain processes synchronously)."""
        transition_type = DepositTrackerPM._transition_event_cls.__type__
        [transition_id] = [
            m.metadata.headers.id
            for m in domain.event_store.store.read("$all")
            if m.metadata.headers.type == transition_type
        ]
        assert _newest_message_id(domain) == transition_id  # precondition
        return transition_id

    def test_transition_as_last_write_is_a_noop(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        transition_id = self._transition_id(domain)

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(transition_id) == []

    def test_transition_as_last_write_does_not_hide_a_lost_event_row(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        [event_id] = _deposited_message_ids(domain)
        outbox_repo._dao._delete_all()
        transition_id = self._transition_id(domain)

        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(event_id)) == 1
        assert outbox_repo.find_all_by_message_id(transition_id) == []


@pytest.mark.no_test_domain
class TestReconcilePartitionKey:
    def test_rebuilt_row_carries_the_unit_of_work_partition_key(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (
                SequencedDepositHandler,
                {"part_of": Account, "sequential_by": "account_id"},
            ),
        )
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            account = _deposit(domain)
            [event_id] = _deposited_message_ids(domain)
            [original] = outbox_repo.find_all_by_message_id(event_id)
            assert original.partition_key == str(account.id)  # precondition

            outbox_repo._dao._delete_all()
            assert reconcile_outbox(domain) == 1

            [rebuilt] = outbox_repo.find_all_by_message_id(event_id)
            assert rebuilt.partition_key == original.partition_key

    def test_rebuilt_row_has_no_partition_key_without_sequential_by(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        [event_id] = _deposited_message_ids(domain)
        outbox_repo._dao._delete_all()

        assert reconcile_outbox(domain) == 1
        [rebuilt] = outbox_repo.find_all_by_message_id(event_id)
        assert rebuilt.partition_key is None


@pytest.mark.no_test_domain
class TestOutboxedEventPredicate:
    @pytest.mark.parametrize(
        "message",
        [
            Message(data={}),
            Message(data={}, metadata=Metadata(headers=MessageHeaders(id="m-1"))),
        ],
        ids=["no-metadata", "no-type"],
    )
    def test_message_without_a_type_string_does_not_qualify(
        self, domain_and_repo, message
    ):
        domain, _ = domain_and_repo
        assert _is_outboxed_event(domain, message) is False

    def test_own_aggregate_event_qualifies(self, domain_and_repo):
        domain, _ = domain_and_repo
        _deposit(domain)
        message = domain.event_store.store.read_last_message("$all")
        assert message.metadata.headers.type == Deposited.__type__
        assert _is_outboxed_event(domain, message) is True


@pytest.mark.message_db
@pytest.mark.no_test_domain
class TestReconcileTwoDomainsOnSharedMessageDB:
    """Two domains write to one Message-DB. Reconciling domain A must neither
    stop at nor repair domain B's events."""

    @pytest.fixture
    def domains(self, tmp_path):
        event_store = {"provider": "message_db", "database_uri": MESSAGE_DB_URI}
        domain_a = _make_domain(tmp_path, event_store=event_store)
        domain_b = _make_foreign_domain(event_store=event_store)
        with domain_a.domain_context():
            outbox_repo = _create_tables(domain_a)
        yield domain_a, domain_b, outbox_repo
        domain_a.event_store.store.close()
        domain_b.event_store.store.close()

    def _write_a_then_b(self, domain_a, domain_b):
        with domain_a.domain_context():
            _deposit(domain_a)
            [own_id] = _deposited_message_ids(domain_a)
        with domain_b.domain_context():
            shipment = Shipment()
            shipment.raise_(Shipped(shipment_id=shipment.id))
            domain_b.repository_for(Shipment).add(shipment)
            foreign_id = _newest_message_id(domain_b)
        with domain_a.domain_context():
            assert _newest_message_id(domain_a) == foreign_id  # precondition
        return own_id, foreign_id

    def test_foreign_tail_with_nothing_missing_is_a_noop(self, domains):
        domain_a, domain_b, outbox_repo = domains
        _, foreign_id = self._write_a_then_b(domain_a, domain_b)

        assert reconcile_outbox(domain_a) == 0
        with domain_a.domain_context():
            assert outbox_repo.find_all_by_message_id(foreign_id) == []

    def test_lost_row_behind_foreign_tail_is_repaired_alone(self, domains):
        domain_a, domain_b, outbox_repo = domains
        own_id, foreign_id = self._write_a_then_b(domain_a, domain_b)
        with domain_a.domain_context():
            outbox_repo._dao._delete_all()

        assert reconcile_outbox(domain_a) == 1
        with domain_a.domain_context():
            assert len(outbox_repo.find_all_by_message_id(own_id)) == 1
            assert outbox_repo.find_all_by_message_id(foreign_id) == []
