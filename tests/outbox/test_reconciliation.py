"""Reconciliation of the ADR-0015 crash window: events durable in the event
store whose relational outbox row did not land."""

import logging

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.upcaster import BaseUpcaster
from protean.domain import Domain
from protean.fields import Identifier, Integer, String
from protean.utils.eventing import Message, MessageHeaders, Metadata
from protean.utils.mixins import handle
from protean.utils.outbox import OutboxStatus, _is_outboxed_event, reconcile_outbox
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


# --- Ownership filter ---------------------------------------------------------
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


class Ledger(BaseAggregate):
    status = Integer(default=0)


class Posted(BaseEvent):
    ledger_id = Identifier(required=True)


class Report(BaseAggregate):
    title = String(default="")


class ReportFiled(BaseEvent):
    report_id = Identifier(required=True)


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


def _make_domain_with(tmp_path, *elements, before_init=None):
    """Like ``_make_domain`` but registers extra ``(cls, kwargs)`` elements
    and runs *before_init* on the domain before ``init``."""
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
    if before_init is not None:
        before_init(domain)
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

    def test_newest_own_event_with_its_row_stops_the_repair(
        self, domain_and_repo, foreign_domain
    ):
        """When the newest own event behind a foreign tail has its row, the last
        commit finished. An older own event whose published row was cleaned up
        must not be rebuilt and published again."""
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        _deposit(domain)
        older_id, newer_id = _deposited_message_ids(domain)
        outbox_repo._dao.delete(outbox_repo.find_all_by_message_id(older_id)[0])
        _append_foreign_event(domain, foreign_domain)

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(older_id) == []
        assert len(outbox_repo.find_all_by_message_id(newer_id)) == 1

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

    def test_externally_registered_foreign_event_is_skipped(
        self, tmp_path, foreign_domain
    ):
        """A consumer domain maps the foreign type string to the foreign class,
        which still carries ``part_of`` the foreign aggregate. The event is not
        in the consumer's own registry, so it gets no row."""
        domain = _make_domain_with(
            tmp_path,
            before_init=lambda d: d.register_external_event(Shipped, Shipped.__type__),
        )
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            foreign_id = _append_foreign_event(domain, foreign_domain)

            assert reconcile_outbox(domain) == 0
            assert outbox_repo.find_all_by_message_id(foreign_id) == []

    def test_foreign_alias_of_a_local_event_is_skipped(self, tmp_path):
        """A foreign type string mapped onto a class this domain also registers
        resolves to the local class, but the unit of work never writes it."""
        domain = _make_domain_with(
            tmp_path,
            before_init=lambda d: d.register_external_event(
                Deposited, "Other.Deposited.v1"
            ),
        )
        with domain.domain_context():
            alias = Message(
                data={},
                metadata=Metadata(
                    headers=MessageHeaders(id="m-1", type="Other.Deposited.v1")
                ),
            )
            assert domain._events_and_commands["Other.Deposited.v1"] is Deposited
            assert _is_outboxed_event(domain, alias, "default") is False


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
    @pytest.fixture
    def partitioned(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (
                SequencedDepositHandler,
                {"part_of": Account, "sequential_by": "account_id"},
            ),
            (Ledger, {}),
            (Posted, {"part_of": Ledger}),
        )
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            domain.repository_for(Ledger)._dao
            provider = domain.providers["default"]
            provider._metadata.create_all(provider._engine)
            yield domain, outbox_repo

    def _deposit_keyed(self, domain, key):
        """Raise a deposit whose ``sequential_by`` field differs from the
        aggregate id, so a key read from the wrong field would not match."""
        account = Account(balance=100)
        account.raise_(Deposited(account_id=key, amount=100))
        domain.repository_for(Account).add(account)
        assert key != account.id  # precondition
        return domain.event_store.store.read_last_message("$all").metadata.headers.id

    def _post(self, domain):
        ledger = Ledger()
        ledger.raise_(Posted(ledger_id=ledger.id))
        domain.repository_for(Ledger).add(ledger)
        return domain.event_store.store.read_last_message("$all").metadata.headers.id

    def test_rebuilt_row_carries_the_unit_of_work_partition_key(
        self, partitioned, caplog
    ):
        domain, outbox_repo = partitioned
        event_id = self._deposit_keyed(domain, "key-7")
        [original] = outbox_repo.find_all_by_message_id(event_id)
        assert original.partition_key == "key-7"  # precondition

        outbox_repo._dao._delete_all()
        with caplog.at_level(logging.ERROR, logger="protean.utils.outbox"):
            assert reconcile_outbox(domain) == 1
        assert "as abandoned" not in caplog.text

        [rebuilt] = outbox_repo.find_all_by_message_id(event_id)
        assert rebuilt.partition_key == original.partition_key

    def test_unpartitioned_category_gets_no_key_beside_a_partitioned_one(
        self, partitioned
    ):
        domain, outbox_repo = partitioned
        deposit_id = self._deposit_keyed(domain, "key-7")
        post_id = self._post(domain)
        outbox_repo._dao._delete_all()

        assert reconcile_outbox(domain) == 2
        [deposit_row] = outbox_repo.find_all_by_message_id(deposit_id)
        [post_row] = outbox_repo.find_all_by_message_id(post_id)
        assert deposit_row.partition_key == "key-7"
        assert post_row.partition_key is None

    def test_a_key_that_no_longer_validates_does_not_block_the_repair(
        self, partitioned, caplog
    ):
        """The backfill suffix changed after the events were written, so one
        stored key is now reserved. That row is saved as abandoned, so it is
        never published without its key, and the other lost row keeps its key."""
        domain, outbox_repo = partitioned
        stale_id = self._deposit_keyed(domain, "key-7")
        good_id = self._deposit_keyed(domain, "key-8")
        outbox_repo._dao._delete_all()
        domain.config["server"]["priority_lanes"] = {"backfill_suffix": "key-7"}

        with caplog.at_level(logging.ERROR, logger="protean.utils.outbox"):
            assert reconcile_outbox(domain) == 2
        assert f"saving the row for message {stale_id} as abandoned" in caplog.text
        assert str(good_id) not in caplog.text
        [stale_row] = outbox_repo.find_all_by_message_id(stale_id)
        [good_row] = outbox_repo.find_all_by_message_id(good_id)
        assert stale_row.status == OutboxStatus.ABANDONED.value
        assert "partition_key could not be computed" in stale_row.last_error["message"]
        assert stale_row.last_processed_at is not None
        assert good_row.status == OutboxStatus.PENDING.value
        assert good_row.partition_key == "key-8"

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
        assert _is_outboxed_event(domain, message, "default") is False

    def test_own_aggregate_event_qualifies(self, domain_and_repo):
        domain, _ = domain_and_repo
        _deposit(domain)
        message = domain.event_store.store.read_last_message("$all")
        assert message.metadata.headers.type == Deposited.__type__
        assert _is_outboxed_event(domain, message, "default") is True


@pytest.mark.no_test_domain
class TestReconcileHonorsTheProvider:
    """Each event's row lives in the outbox of its aggregate's provider, so
    reconciling one provider must skip events of aggregates on another."""

    @pytest.fixture
    def domain(self, tmp_path):
        def add_analytics_database(domain):
            domain.config["databases"]["analytics"] = {
                "provider": "sqlite",
                "database_uri": f"sqlite:///{tmp_path / 'analytics.db'}",
            }

        domain = _make_domain_with(
            tmp_path,
            (Report, {"provider": "analytics"}),
            (ReportFiled, {"part_of": Report}),
            before_init=add_analytics_database,
        )
        with domain.domain_context():
            _create_tables(domain)
            provider = domain.providers["analytics"]
            domain.repository_for(Report)._dao
            domain._get_outbox_repo("analytics")._dao
            provider._metadata.create_all(provider._engine)
            yield domain

    def _file_report(self, domain):
        report = Report(title="Q3")
        report.raise_(ReportFiled(report_id=report.id))
        domain.repository_for(Report).add(report)
        return _newest_message_id(domain)

    def test_other_providers_committed_event_at_the_tail_is_a_noop(self, domain):
        _deposit(domain)
        report_event_id = self._file_report(domain)
        analytics_repo = domain._get_outbox_repo("analytics")
        default_repo = domain._get_outbox_repo("default")
        assert len(analytics_repo.find_all_by_message_id(report_event_id)) == 1

        assert reconcile_outbox(domain) == 0
        assert default_repo.find_all_by_message_id(report_event_id) == []

    def test_each_provider_repairs_only_its_own_events(self, domain):
        _deposit(domain)
        [deposit_id] = _deposited_message_ids(domain)
        report_event_id = self._file_report(domain)
        default_repo = domain._get_outbox_repo("default")
        analytics_repo = domain._get_outbox_repo("analytics")
        default_repo._dao._delete_all()
        analytics_repo._dao._delete_all()

        assert reconcile_outbox(domain) == 1
        assert len(default_repo.find_all_by_message_id(deposit_id)) == 1
        assert default_repo.find_all_by_message_id(report_event_id) == []

        assert reconcile_outbox(domain, provider_name="analytics") == 1
        assert len(analytics_repo.find_all_by_message_id(report_event_id)) == 1
        assert analytics_repo.find_all_by_message_id(deposit_id) == []


class Withdrawn(BaseEvent):
    account_id = Identifier(required=True)
    amount = Integer(required=True)
    __version__ = 2


class UpcastWithdrawn(BaseUpcaster):
    def upcast(self, data):
        return data


@pytest.mark.no_test_domain
class TestReconcileRepairsOlderEventVersions:
    """A crash leaves a v1 event without its row, and the next deploy bumps the
    event to v2 with an upcaster. The v1 event is still this domain's."""

    def _v1_message(self):
        class Withdrawn(BaseEvent):  # the same event before the version bump
            account_id = Identifier(required=True)
            amount = Integer(required=True)

        old_domain = Domain(name="Reconcile")
        old_domain.register(Account)
        old_domain.register(Withdrawn, part_of=Account)
        old_domain.init(traverse=False)
        with old_domain.domain_context():
            account = Account()
            account.raise_(Withdrawn(account_id=account.id, amount=5))
            return Message.from_domain_object(account._events[-1])

    def test_lost_row_of_an_older_version_is_repaired(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (Withdrawn, {"part_of": Account}),
            before_init=lambda d: d.upcaster(
                UpcastWithdrawn, event_type=Withdrawn, from_version=1, to_version=2
            ),
        )
        message = self._v1_message()
        assert message.metadata.headers.type == "Reconcile.Withdrawn.v1"
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            domain.event_store.store._write(
                message.metadata.headers.stream,
                message.metadata.headers.type,
                message.data,
                metadata=message.metadata.to_dict(),
            )

            assert reconcile_outbox(domain) == 1
            [row] = outbox_repo.find_all_by_message_id(message.metadata.headers.id)
            assert row.type == "Reconcile.Withdrawn.v1"


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
