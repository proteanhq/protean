"""Reconciliation of the ADR-0015 crash window: events durable in the event
store whose relational outbox row did not land."""

import logging
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.upcaster import BaseUpcaster
from protean.domain import Domain
from protean.fields import Identifier, Integer, String
from protean.server.engine import Engine
from protean.utils import outbox as outbox_module
from protean.utils.eventing import Message, MessageHeaders, Metadata
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from protean.utils.outbox import (
    Outbox,
    OutboxStatus,
    _is_repairable_event,
    _resolve_outboxed_event_class,
    _written_after,
    reconcile_outbox,
)
from tests.shared import MESSAGE_DB_URI, POSTGRES_URI, FrozenClock

# Reconcile repairs only events of event-sourced aggregates, so the repair
# tests raise events on the event-sourced ``Wallet``. The state-based
# ``Account`` stands for the aggregates reconcile must skip.


class Funded(BaseEvent):
    wallet_id = Identifier(required=True)
    amount = Integer(required=True)


class Credited(BaseEvent):
    wallet_id = Identifier(required=True)
    amount = Integer(required=True)


class Withdrawn(BaseEvent):
    wallet_id = Identifier(required=True)
    amount = Integer(required=True)
    __version__ = 2


class Wallet(BaseAggregate):
    balance = Integer(default=0)

    # Any of these events can be a wallet's first, and a wallet rebuilt from
    # its events starts with no balance, so each handler treats ``None`` as 0.
    @apply
    def funded(self, event: Funded) -> None:
        self.balance = (self.balance or 0) + event.amount

    @apply
    def credited(self, event: Credited) -> None:
        self.balance = (self.balance or 0) + event.amount

    @apply
    def withdrawn(self, event: Withdrawn) -> None:
        self.balance = (self.balance or 0) - event.amount


class Account(BaseAggregate):
    balance = Integer(default=0)


class Deposited(BaseEvent):
    account_id = Identifier(required=True)
    amount = Integer(required=True)


class Audited(BaseEvent):
    account_id = Identifier(required=True)


def _register_wallet_and_account(domain):
    domain.register(Wallet, event_sourced=True)
    domain.register(Funded, part_of=Wallet)
    domain.register(Account)
    domain.register(Deposited, part_of=Account)


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
    _register_wallet_and_account(domain)
    domain.init(traverse=False)
    return domain


def _fund(domain):
    wallet = Wallet()
    wallet.raise_(Funded(wallet_id=wallet.id, amount=100))
    domain.repository_for(Wallet).add(wallet)
    return wallet


def _deposit(domain):
    account = Account(balance=100)
    account.raise_(Deposited(account_id=account.id, amount=100))
    domain.repository_for(Account).add(account)
    return account


def _newest_message_id(domain):
    return domain.event_store.store.read_last_message("$all").metadata.headers.id


def _lose_rows(outbox_repo, message_id):
    """Delete every outbox row of *message_id*, as a crash before the outbox
    commit leaves it, while the other messages keep their rows."""
    rows = outbox_repo.find_all_by_message_id(message_id)
    assert rows
    for row in rows:
        outbox_repo._dao.delete(row)


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
        _fund(domain)
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

    def test_rebuilt_rows_are_numbered_in_store_order(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        for _ in range(3):
            _fund(domain)
        store_order = [
            m.metadata.headers.id
            for m in domain.event_store.store.read("$all")
            if m.metadata.headers.type == Funded.__type__
        ]
        assert len(store_order) == 3

        outbox_repo._dao._delete_all()
        assert reconcile_outbox(domain) == 3

        rows = outbox_repo._dao.query.all().items
        assert len(rows) == 3
        by_message = {row.message_id: row.sequence_number for row in rows}
        assert [by_message[mid] for mid in store_order] == [0, 1, 2]

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
            _fund(domain)
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
        _fund(domain)
        _fund(domain)
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

    def test_reconcile_is_a_noop_when_nothing_is_missing(
        self, domain_and_repo, monkeypatch
    ):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        store = domain.event_store.store

        positions = []
        real_read = store.read

        def spy(*args, **kwargs):
            positions.append(kwargs.get("position"))
            return real_read(*args, **kwargs)

        monkeypatch.setattr(store, "read", spy)

        # Every run reads the window once, and finds every row in place.
        assert reconcile_outbox(domain) == 0
        assert positions == [0]
        assert len(outbox_repo._dao.query.all().items) == 1

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
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        message_id = _newest_message_id(domain)

        # Simulate the crash gap: the event is durable, its outbox row is not.
        outbox_repo._dao._delete_all()
        assert outbox_repo.find_all_by_message_id(message_id) == []

        engine = Engine(domain, test_mode=True)
        assert engine._reconcile_outbox_on_startup() == 1
        assert len(outbox_repo.find_all_by_message_id(message_id)) == 1


@pytest.mark.no_test_domain
class TestReconcileRepairsALostRowBehindALaterCommit:
    """Several processes can write to one domain. A crash in one process loses
    an event's outbox row, and another process then commits a later event with
    its row. The lost row must still be rebuilt."""

    def test_lost_row_behind_a_later_commit_is_repaired(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        _fund(domain)
        older_id, newer_id = _funded_message_ids(domain)
        _lose_rows(outbox_repo, older_id)

        assert reconcile_outbox(domain) == 1
        rows = outbox_repo.find_all_by_message_id(older_id)
        assert len(rows) == 1
        assert rows[0].target_broker == "default"
        assert len(outbox_repo.find_all_by_message_id(newer_id)) == 1

    def test_engine_startup_sweep_repairs_a_lost_row_behind_a_later_commit(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        _fund(domain)
        older_id, newer_id = _funded_message_ids(domain)
        _lose_rows(outbox_repo, older_id)

        engine = Engine(domain, test_mode=True)
        assert engine._reconcile_outbox_on_startup() == 1
        assert len(outbox_repo.find_all_by_message_id(older_id)) == 1
        assert len(outbox_repo.find_all_by_message_id(newer_id)) == 1

    def test_every_row_in_place_is_a_noop(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        _fund(domain)

        assert reconcile_outbox(domain) == 0
        assert len(outbox_repo._dao.query.all().items) == 2

    def test_only_the_lost_row_in_the_middle_is_rebuilt(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        for _ in range(3):
            _fund(domain)
        first_id, middle_id, last_id = _funded_message_ids(domain)
        _lose_rows(outbox_repo, middle_id)

        assert reconcile_outbox(domain) == 1
        for message_id in (first_id, middle_id, last_id):
            assert len(outbox_repo.find_all_by_message_id(message_id)) == 1

    def test_lookup_finds_every_row_past_the_default_query_limit(self, domain_and_repo):
        """The outbox query returns 100 rows unless told otherwise. A window
        with more events must still see every existing row."""
        domain, outbox_repo = domain_and_repo
        for _ in range(105):
            _fund(domain)
        message_ids = _funded_message_ids(domain)
        assert len(message_ids) == 105

        existing = outbox_module._existing_brokers_by_message(outbox_repo, message_ids)
        assert existing == {message_id: {"default"} for message_id in message_ids}

        _lose_rows(outbox_repo, message_ids[2])
        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(message_ids[2])) == 1
        assert len(outbox_repo._dao.query.limit(None).all().items) == 105

    def test_lookup_spans_several_chunks(self, domain_and_repo, monkeypatch):
        monkeypatch.setattr(outbox_module, "_BROKER_LOOKUP_CHUNK_SIZE", 2)
        domain, outbox_repo = domain_and_repo
        for _ in range(5):
            _fund(domain)
        message_ids = _funded_message_ids(domain)
        _lose_rows(outbox_repo, message_ids[3])

        existing = outbox_module._existing_brokers_by_message(outbox_repo, message_ids)
        assert existing == {
            message_id: set() if message_id == message_ids[3] else {"default"}
            for message_id in message_ids
        }
        assert reconcile_outbox(domain) == 1
        for message_id in message_ids:
            assert len(outbox_repo.find_all_by_message_id(message_id)) == 1

    def test_lookup_reads_a_legacy_null_broker_as_the_default(self):
        """A legacy row holding NULL in ``target_broker`` counts as the
        default broker's row, so reconcile does not rebuild it and publish the
        event again. The column is NOT NULL, so a stub query returns the row."""
        outbox_repo = MagicMock()
        query = outbox_repo._dao.query.filter.return_value.only.return_value
        query.limit.return_value.all.return_value.items = [
            SimpleNamespace(message_id="m1", target_broker=None)
        ]

        existing = outbox_module._existing_brokers_by_message(outbox_repo, ["m1"])
        assert existing == {"m1": {"default"}}


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
        _fund(domain)
        # _newest_message_id reads read_last_message("$all") — the fixed path.
        message_id = _newest_message_id(domain)
        assert len(outbox_repo.find_all_by_message_id(message_id)) == 1

        outbox_repo._dao._delete_all()  # simulate the crash window
        assert outbox_repo.find_all_by_message_id(message_id) == []

        # Before the fix this returned 0 (read_last_message("$all") was None).
        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(message_id)) == 1

    def test_lost_row_behind_a_later_commit_is_repaired(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        _fund(domain)
        older_id, newer_id = _funded_message_ids(domain)
        _lose_rows(outbox_repo, older_id)

        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(older_id)) == 1
        assert len(outbox_repo.find_all_by_message_id(newer_id)) == 1


@pytest.mark.no_test_domain
class TestReconcileBesideALiveWriter:
    def test_sweep_skips_a_row_a_live_commit_wrote_after_its_check(
        self, domain_and_repo, monkeypatch
    ):
        """A live unit of work commits the row after the sweep found it
        missing. The sweep keeps that row, skips its own copy, and counts
        nothing."""
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        message_id = _newest_message_id(domain)
        outbox_repo._dao._delete_all()  # simulate the crash window

        live_dao = domain.providers["default"].get_dao(
            Outbox, outbox_repo._database_model
        )
        live_rows = []
        real_rebuilt_partition_key = outbox_module._rebuilt_partition_key

        # The sweep computes the row's partition key after it has found the row
        # missing and before it saves its copy, so the live row lands in between.
        def live_commit_first(message, *args):
            if not live_rows:
                headers = message.metadata.headers
                live_rows.append(
                    Outbox.create_message(
                        message_id=headers.id,
                        stream_name=headers.stream,
                        message_type=headers.type,
                        data=message.data,
                        metadata=message.metadata,
                    )
                )
                live_dao.outside_uow().save(live_rows[0])
            return real_rebuilt_partition_key(message, *args)

        monkeypatch.setattr(outbox_module, "_rebuilt_partition_key", live_commit_first)

        assert reconcile_outbox(domain) == 0

        rows = outbox_repo.find_all_by_message_id(message_id)
        assert [row.id for row in rows] == [live_rows[0].id]


@pytest.mark.postgresql
@pytest.mark.message_db
@pytest.mark.no_test_domain
class TestReconcileBesideALiveUnitOfWorkOnPostgres:
    """The startup sweep runs while a unit of work has appended its event to
    Message DB and not yet saved the event's outbox row."""

    SCHEMA = "reconcile_beside_live_uow"

    @pytest.fixture
    def domain(self):
        domain = Domain(name="ReconcileLive")
        domain.config["databases"]["default"] = {
            "provider": "postgresql",
            "database_uri": POSTGRES_URI,
            "schema": self.SCHEMA,
        }
        domain.config["event_store"] = {
            "provider": "message_db",
            "database_uri": MESSAGE_DB_URI,
        }
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}
        _register_wallet_and_account(domain)
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            # Tables of their own, so this domain's outbox table does not meet
            # one another test left in the shared database.
            with provider._engine.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {self.SCHEMA} CASCADE"))
                conn.execute(text(f"CREATE SCHEMA {self.SCHEMA}"))
            domain.repository_for(Account)._dao
            domain._get_outbox_repo("default")._dao
            provider._metadata.create_all(provider._engine)
            try:
                yield domain
            finally:
                provider._scoped_session_cls.remove()
                with provider._engine.begin() as conn:
                    conn.execute(text(f"DROP SCHEMA IF EXISTS {self.SCHEMA} CASCADE"))
                provider.close()
                domain.event_store.store.close()

    def test_the_live_commit_succeeds_and_one_row_is_kept(self, domain, monkeypatch):
        store = domain.event_store.store
        real_append = store.append
        sweep_results = []
        sweep_errors = []

        def sweep():
            try:
                sweep_results.append(reconcile_outbox(domain))
            except Exception as exc:  # reported by the assertion below
                sweep_errors.append(exc)

        def append_then_sweep(*args, **kwargs):
            result = real_append(*args, **kwargs)
            if not sweep_results and not sweep_errors:
                thread = threading.Thread(target=sweep)
                thread.start()
                thread.join(timeout=30)
            return result

        monkeypatch.setattr(store, "append", append_then_sweep)

        _fund(domain)
        monkeypatch.undo()

        assert sweep_errors == []
        assert sweep_results == [1]
        message_id = _newest_message_id(domain)
        outbox_repo = domain._get_outbox_repo("default")
        rows = outbox_repo.find_all_by_message_id(message_id)
        assert [row.target_broker for row in rows] == ["default"]


# --- Ownership filter ---------------------------------------------------------
#
# Only events raised by this domain's aggregates get outbox rows from the unit
# of work, so only those may be repaired. Foreign events in a shared store,
# commands, and process manager transitions must be skipped.


class Fund(BaseCommand):
    wallet_id = Identifier(required=True)
    amount = Integer(required=True)


class WalletCommandHandler(BaseCommandHandler):
    @handle(Fund)
    def fund(self, command):
        pass


class FundTrackerPM(BaseProcessManager):
    wallet_id = Identifier()

    @handle(Funded, start=True, correlate="wallet_id")
    def on_funded(self, event):
        self.wallet_id = event.wallet_id


class SequencedFundHandler(BaseEventHandler):
    @handle(Funded)
    def on_funded(self, event):
        pass


class Shipment(BaseAggregate):
    status = Integer(default=0)


class Shipped(BaseEvent):
    shipment_id = Identifier(required=True)


class Posted(BaseEvent):
    ledger_id = Identifier(required=True)


class Ledger(BaseAggregate):
    status = Integer(default=0)

    @apply
    def posted(self, event: Posted) -> None:
        self.status = 1


class ReportFiled(BaseEvent):
    report_id = Identifier(required=True)


class Report(BaseAggregate):
    title = String(default="")

    @apply
    def filed(self, event: ReportFiled) -> None:
        pass


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


def _funded_message_ids(domain):
    return [
        m.metadata.headers.id
        for m in domain.event_store.store.read("$all")
        if m.metadata.headers.type == Funded.__type__
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
    _register_wallet_and_account(domain)
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
        _fund(domain)
        foreign_id = _append_foreign_event(domain, foreign_domain)
        assert _newest_message_id(domain) == foreign_id  # precondition

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(foreign_id) == []

    def test_lost_row_behind_a_foreign_tail_is_repaired_alone(
        self, domain_and_repo, foreign_domain
    ):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        [own_id] = _funded_message_ids(domain)
        outbox_repo._dao._delete_all()
        foreign_id = _append_foreign_event(domain, foreign_domain)

        assert reconcile_outbox(domain) == 1
        rows = outbox_repo.find_all_by_message_id(own_id)
        assert len(rows) == 1
        assert rows[0].type == Funded.__type__
        assert outbox_repo.find_all_by_message_id(foreign_id) == []

    def test_lost_row_behind_a_later_own_commit_and_a_foreign_tail_is_repaired(
        self, domain_and_repo, foreign_domain
    ):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        _fund(domain)
        older_id, newer_id = _funded_message_ids(domain)
        _lose_rows(outbox_repo, older_id)
        foreign_id = _append_foreign_event(domain, foreign_domain)

        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(older_id)) == 1
        assert len(outbox_repo.find_all_by_message_id(newer_id)) == 1
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
        _fund(domain)
        [own_id] = _funded_message_ids(domain)
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
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        [own_id] = _funded_message_ids(domain)
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
            before_init=lambda d: d.register_external_event(Funded, "Other.Funded.v1"),
        )
        with domain.domain_context():
            alias = Message(
                data={},
                metadata=Metadata(
                    headers=MessageHeaders(id="m-1", type="Other.Funded.v1")
                ),
            )
            assert domain._events_and_commands["Other.Funded.v1"] is Funded
            assert _resolve_outboxed_event_class(domain, alias, "default") is None


@pytest.mark.no_test_domain
class TestReconcileSkipsCommands:
    @pytest.fixture
    def domain_and_repo(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (Fund, {"part_of": Wallet}),
            (WalletCommandHandler, {"part_of": Wallet}),
        )
        with domain.domain_context():
            yield domain, _create_tables(domain)

    def _process_fund(self, domain):
        command = Fund(wallet_id="acc-1", amount=10)
        domain.process(command, asynchronous=True)
        [command_id] = [
            m.metadata.headers.id
            for m in domain.event_store.store.read("$all")
            if m.metadata.headers.type == Fund.__type__
        ]
        assert _newest_message_id(domain) == command_id  # precondition
        return command_id

    def test_command_as_last_write_is_a_noop(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        command_id = self._process_fund(domain)

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(command_id) == []

    def test_command_as_last_write_does_not_hide_a_lost_event_row(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        [event_id] = _funded_message_ids(domain)
        outbox_repo._dao._delete_all()
        command_id = self._process_fund(domain)

        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(event_id)) == 1
        assert outbox_repo.find_all_by_message_id(command_id) == []


@pytest.mark.no_test_domain
class TestReconcileSkipsProcessManagerTransitions:
    @pytest.fixture
    def domain_and_repo(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (FundTrackerPM, {"stream_categories": ["reconcile::wallet"]}),
        )
        with domain.domain_context():
            yield domain, _create_tables(domain)

    def _transition_id(self, domain):
        """Return the id of the transition event the process manager appended
        when it handled the funding event (the test domain processes synchronously)."""
        transition_type = FundTrackerPM._transition_event_cls.__type__
        [transition_id] = [
            m.metadata.headers.id
            for m in domain.event_store.store.read("$all")
            if m.metadata.headers.type == transition_type
        ]
        assert _newest_message_id(domain) == transition_id  # precondition
        return transition_id

    def test_transition_as_last_write_is_a_noop(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        transition_id = self._transition_id(domain)

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(transition_id) == []

    def test_transition_as_last_write_does_not_hide_a_lost_event_row(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        [event_id] = _funded_message_ids(domain)
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
                SequencedFundHandler,
                {"part_of": Wallet, "sequential_by": "wallet_id"},
            ),
            (Ledger, {"event_sourced": True}),
            (Posted, {"part_of": Ledger}),
        )
        with domain.domain_context():
            yield domain, _create_tables(domain)

    def _fund_keyed(self, domain, key):
        """Raise a funding event whose ``sequential_by`` field differs from the
        aggregate id, so a key read from the wrong field would not match."""
        wallet = Wallet()
        wallet.raise_(Funded(wallet_id=key, amount=100))
        domain.repository_for(Wallet).add(wallet)
        assert key != wallet.id  # precondition
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
        event_id = self._fund_keyed(domain, "key-7")
        [original] = outbox_repo.find_all_by_message_id(event_id)
        assert original.partition_key == "key-7"  # precondition

        outbox_repo._dao._delete_all()
        with caplog.at_level(logging.ERROR, logger="protean.utils.outbox"):
            assert reconcile_outbox(domain) == 1
        assert "as abandoned" not in caplog.text

        [rebuilt] = outbox_repo.find_all_by_message_id(event_id)
        assert rebuilt.partition_key == original.partition_key

    def test_rebuilt_row_carries_the_unit_of_work_stream_category(self, partitioned):
        domain, outbox_repo = partitioned
        event_id = self._fund_keyed(domain, "key-7")
        [original] = outbox_repo.find_all_by_message_id(event_id)
        assert original.stream_category == Wallet.meta_.stream_category

        outbox_repo._dao._delete_all()
        assert reconcile_outbox(domain) == 1

        [rebuilt] = outbox_repo.find_all_by_message_id(event_id)
        assert rebuilt.stream_category == Wallet.meta_.stream_category

    def test_unpartitioned_category_gets_no_key_beside_a_partitioned_one(
        self, partitioned
    ):
        domain, outbox_repo = partitioned
        fund_id = self._fund_keyed(domain, "key-7")
        post_id = self._post(domain)
        outbox_repo._dao._delete_all()

        assert reconcile_outbox(domain) == 2
        [fund_row] = outbox_repo.find_all_by_message_id(fund_id)
        [post_row] = outbox_repo.find_all_by_message_id(post_id)
        assert fund_row.partition_key == "key-7"
        assert post_row.partition_key is None

    def test_a_key_that_no_longer_validates_does_not_block_the_repair(
        self, partitioned, caplog
    ):
        """The backfill suffix changed after the events were written, so one
        stored key is now reserved. That row is saved as abandoned, so it is
        never published without its key, and the other lost row keeps its key."""
        domain, outbox_repo = partitioned
        stale_id = self._fund_keyed(domain, "key-7")
        good_id = self._fund_keyed(domain, "key-8")
        outbox_repo._dao._delete_all()
        domain.config["server"]["priority_lanes"] = {"backfill_suffix": "key-7"}

        with caplog.at_level(logging.ERROR, logger="protean.utils.outbox"):
            assert reconcile_outbox(domain) == 2
        assert f"saving the row(s) for message {stale_id} as abandoned" in caplog.text
        assert str(good_id) not in caplog.text
        [stale_row] = outbox_repo.find_all_by_message_id(stale_id)
        [good_row] = outbox_repo.find_all_by_message_id(good_id)
        assert stale_row.status == OutboxStatus.ABANDONED.value
        assert "partition_key could not be computed" in stale_row.last_error["message"]
        assert stale_row.last_processed_at is not None
        assert stale_row.last_error["reason"] == "Invalid partition key"
        assert good_row.status == OutboxStatus.PENDING.value
        assert good_row.partition_key == "key-8"

    def test_rebuilt_row_has_no_partition_key_without_sequential_by(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        [event_id] = _funded_message_ids(domain)
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
        assert _resolve_outboxed_event_class(domain, message, "default") is None

    def test_own_aggregate_event_qualifies(self, domain_and_repo):
        domain, _ = domain_and_repo
        _fund(domain)
        message = domain.event_store.store.read_last_message("$all")
        assert message.metadata.headers.type == Funded.__type__
        assert _resolve_outboxed_event_class(domain, message, "default") is not None

    def test_only_an_event_sourced_aggregates_event_is_repairable(
        self, domain_and_repo
    ):
        """The unit of work writes a row for both events, but reconcile
        rebuilds only the event-sourced aggregate's."""
        domain, _ = domain_and_repo
        _fund(domain)
        funded = domain.event_store.store.read_last_message("$all")
        _deposit(domain)
        deposited = domain.event_store.store.read_last_message("$all")
        assert deposited.metadata.headers.type == Deposited.__type__

        assert _resolve_outboxed_event_class(domain, funded, "default") is not None
        assert _resolve_outboxed_event_class(domain, deposited, "default") is not None
        assert _is_repairable_event(domain, funded, "default") is True
        assert _is_repairable_event(domain, deposited, "default") is False


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
            (Report, {"provider": "analytics", "event_sourced": True}),
            (ReportFiled, {"part_of": Report}),
            before_init=add_analytics_database,
        )
        with domain.domain_context():
            _create_tables(domain)
            provider = domain.providers["analytics"]
            domain._get_outbox_repo("analytics")._dao
            provider._metadata.create_all(provider._engine)
            yield domain

    def _file_report(self, domain):
        report = Report(title="Q3")
        report.raise_(ReportFiled(report_id=report.id))
        domain.repository_for(Report).add(report)
        return _newest_message_id(domain)

    def test_other_providers_committed_event_at_the_tail_is_a_noop(self, domain):
        _fund(domain)
        report_event_id = self._file_report(domain)
        analytics_repo = domain._get_outbox_repo("analytics")
        default_repo = domain._get_outbox_repo("default")
        assert len(analytics_repo.find_all_by_message_id(report_event_id)) == 1

        assert reconcile_outbox(domain) == 0
        assert default_repo.find_all_by_message_id(report_event_id) == []

    def test_each_provider_repairs_only_its_own_events(self, domain):
        _fund(domain)
        [fund_id] = _funded_message_ids(domain)
        report_event_id = self._file_report(domain)
        default_repo = domain._get_outbox_repo("default")
        analytics_repo = domain._get_outbox_repo("analytics")
        default_repo._dao._delete_all()
        analytics_repo._dao._delete_all()

        assert reconcile_outbox(domain) == 1
        assert len(default_repo.find_all_by_message_id(fund_id)) == 1
        assert default_repo.find_all_by_message_id(report_event_id) == []

        assert reconcile_outbox(domain, provider_name="analytics") == 1
        assert len(analytics_repo.find_all_by_message_id(report_event_id)) == 1
        assert analytics_repo.find_all_by_message_id(fund_id) == []


class UpcastWithdrawn(BaseUpcaster):
    def upcast(self, data):
        return data


@pytest.mark.no_test_domain
class TestReconcileRepairsOlderEventVersions:
    """A crash leaves a v1 event without its row, and the next deploy bumps the
    event to v2 with an upcaster. The v1 event is still this domain's."""

    def _v1_message(self):
        class Withdrawn(BaseEvent):  # the same event before the version bump
            wallet_id = Identifier(required=True)
            amount = Integer(required=True)

        # A stand-in with the same name gives the stored message the same
        # stream, and leaves the shared event-sourced ``Wallet`` unregistered.
        class Wallet(BaseAggregate):
            balance = Integer(default=0)

        old_domain = Domain(name="Reconcile")
        old_domain.register(Wallet)
        old_domain.register(Withdrawn, part_of=Wallet)
        old_domain.init(traverse=False)
        with old_domain.domain_context():
            wallet = Wallet()
            wallet.raise_(Withdrawn(wallet_id=wallet.id, amount=5))
            return Message.from_domain_object(wallet._events[-1])

    def test_lost_row_of_an_older_version_is_repaired(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (Withdrawn, {"part_of": Wallet}),
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
            _fund(domain_a)
            [own_id] = _funded_message_ids(domain_a)
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


class SequencedCreditHandler(BaseEventHandler):
    @handle(Credited)
    def on_credited(self, event):
        pass


class CreditWallet(BaseCommand):
    amount = Integer(required=True)


class CreditHandler(BaseCommandHandler):
    @handle(CreditWallet)
    def credit(self, command):
        wallet = Wallet()
        wallet.raise_(Credited(wallet_id=wallet.id, amount=command.amount))
        current_domain.repository_for(Wallet).add(wallet)


def _with_external_brokers(*brokers):
    def configure(domain):
        domain.config["outbox"]["external_brokers"] = list(brokers)
        for broker in brokers:
            domain.config["brokers"][broker] = {"provider": "inline"}

    return configure


@pytest.mark.no_test_domain
class TestReconcileExternalBrokers:
    """A ``published`` event gets one outbox row per external broker in the
    same commit as its internal row. Reconcile rebuilds all of them."""

    def _domain(self, tmp_path, *brokers, published=True, elements=()):
        domain = _make_domain_with(
            tmp_path,
            (Credited, {"part_of": Wallet, "published": published}),
            *elements,
            before_init=_with_external_brokers(*brokers),
        )
        return domain

    def _credit(self, domain, key=None):
        wallet = Wallet()
        wallet.raise_(Credited(wallet_id=key or wallet.id, amount=100))
        domain.repository_for(Wallet).add(wallet)
        return domain.event_store.store.read_last_message("$all").metadata.headers.id

    @staticmethod
    def _brokers(outbox_repo, message_id):
        return sorted(
            row.target_broker for row in outbox_repo.find_all_by_message_id(message_id)
        )

    def test_published_event_gets_its_external_row_back(self, tmp_path):
        domain = self._domain(tmp_path, "ext-a")
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain)
            assert self._brokers(outbox_repo, message_id) == ["default", "ext-a"]

            outbox_repo._dao._delete_all()
            assert reconcile_outbox(domain) == 2
            assert self._brokers(outbox_repo, message_id) == ["default", "ext-a"]

    def test_one_row_per_external_broker(self, tmp_path):
        domain = self._domain(tmp_path, "ext-a", "ext-b")
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain)

            outbox_repo._dao._delete_all()
            assert reconcile_outbox(domain) == 3
            assert self._brokers(outbox_repo, message_id) == [
                "default",
                "ext-a",
                "ext-b",
            ]

    def test_rebuilt_external_rows_share_their_events_number(self, tmp_path):
        domain = self._domain(tmp_path, "ext-a")
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_ids = [self._credit(domain) for _ in range(2)]

            outbox_repo._dao._delete_all()
            assert reconcile_outbox(domain) == 4

            numbers = {
                message_id: {
                    row.target_broker: row.sequence_number
                    for row in outbox_repo.find_all_by_message_id(message_id)
                }
                for message_id in message_ids
            }
            assert numbers == {
                message_ids[0]: {"default": 0, "ext-a": 0},
                message_ids[1]: {"default": 1, "ext-a": 1},
            }

    def test_rebuilt_rows_match_what_the_unit_of_work_wrote_at_default_priority(
        self, tmp_path
    ):
        """Raised through a command, so the correlation and causation ids carry
        real values. Priority matches only at the default, since the original
        request's priority is not stored with the event."""
        domain = self._domain(
            tmp_path,
            "ext-a",
            "ext-b",
            elements=(
                (CreditWallet, {"part_of": Wallet}),
                (CreditHandler, {"part_of": Wallet}),
            ),
        )
        fields = (
            "message_id",
            "stream_name",
            "type",
            "data",
            "partition_key",
            "correlation_id",
            "causation_id",
            "priority",
            "status",
        )
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            domain.process(CreditWallet(amount=100), asynchronous=False)
            message_id = _newest_message_id(domain)
            original = {
                row.target_broker: {f: getattr(row, f) for f in fields}
                for row in outbox_repo.find_all_by_message_id(message_id)
            }
            assert sorted(original) == ["default", "ext-a", "ext-b"]
            for row in original.values():
                assert row["correlation_id"] is not None
                assert row["causation_id"] is not None

            outbox_repo._dao._delete_all()
            reconcile_outbox(domain)
            rebuilt = {
                row.target_broker: {f: getattr(row, f) for f in fields}
                for row in outbox_repo.find_all_by_message_id(message_id)
            }
            assert rebuilt == original

    def test_external_rows_carry_the_partition_key(self, tmp_path):
        domain = self._domain(
            tmp_path,
            "ext-a",
            elements=(
                (
                    SequencedCreditHandler,
                    {"part_of": Wallet, "sequential_by": "wallet_id"},
                ),
            ),
        )
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain, key="key-7")

            outbox_repo._dao._delete_all()
            assert reconcile_outbox(domain) == 2
            rows = outbox_repo.find_all_by_message_id(message_id)
            assert len(rows) == 2
            for row in rows:
                assert row.partition_key == "key-7"
                assert row.status == OutboxStatus.PENDING.value

    def test_a_key_that_no_longer_validates_abandons_every_row(self, tmp_path, caplog):
        domain = self._domain(
            tmp_path,
            "ext-a",
            elements=(
                (
                    SequencedCreditHandler,
                    {"part_of": Wallet, "sequential_by": "wallet_id"},
                ),
            ),
        )
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain, key="key-7")
            outbox_repo._dao._delete_all()
            domain.config["server"]["priority_lanes"] = {"backfill_suffix": "key-7"}

            with caplog.at_level(logging.ERROR, logger="protean.utils.outbox"):
                assert reconcile_outbox(domain) == 2
            assert f"saving the row(s) for message {message_id} as abandoned" in (
                caplog.text
            )
            rows = outbox_repo.find_all_by_message_id(message_id)
            assert sorted(row.target_broker for row in rows) == ["default", "ext-a"]
            for row in rows:
                assert row.status == OutboxStatus.ABANDONED.value
                assert row.partition_key is None
                assert row.last_error["reason"] == "Invalid partition key"
                assert (
                    "partition_key could not be computed" in row.last_error["message"]
                )

    def test_older_version_of_a_published_event_gets_its_external_row(self, tmp_path):
        domain = _make_domain_with(
            tmp_path,
            (Withdrawn, {"part_of": Wallet, "published": True}),
            before_init=lambda d: (
                _with_external_brokers("ext-a")(d),
                d.upcaster(
                    UpcastWithdrawn, event_type=Withdrawn, from_version=1, to_version=2
                ),
            ),
        )
        message = TestReconcileRepairsOlderEventVersions()._v1_message()
        assert message.metadata.headers.type == "Reconcile.Withdrawn.v1"
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            domain.event_store.store._write(
                message.metadata.headers.stream,
                message.metadata.headers.type,
                message.data,
                metadata=message.metadata.to_dict(),
            )

            assert reconcile_outbox(domain) == 2
            rows = outbox_repo.find_all_by_message_id(message.metadata.headers.id)
            assert sorted(row.target_broker for row in rows) == ["default", "ext-a"]
            assert {row.type for row in rows} == {"Reconcile.Withdrawn.v1"}

    def test_unpublished_event_gets_only_its_internal_row(self, tmp_path):
        domain = self._domain(tmp_path, "ext-a", published=False)
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain)
            assert self._brokers(outbox_repo, message_id) == ["default"]

            outbox_repo._dao._delete_all()
            assert reconcile_outbox(domain) == 1
            assert self._brokers(outbox_repo, message_id) == ["default"]

    def test_published_event_without_external_brokers_gets_only_its_internal_row(
        self, tmp_path
    ):
        domain = self._domain(tmp_path)
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain)

            outbox_repo._dao._delete_all()
            assert reconcile_outbox(domain) == 1
            assert self._brokers(outbox_repo, message_id) == ["default"]

    def test_lost_external_rows_alone_are_not_repaired(self, tmp_path):
        """A message counts as missing only when its internal row is missing,
        since the unit of work saves all of its rows in one commit."""
        domain = self._domain(tmp_path, "ext-a")
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain)
            for row in outbox_repo.find_all_by_message_id(message_id):
                if row.target_broker == "ext-a":
                    outbox_repo._dao.delete(row)

            assert reconcile_outbox(domain) == 0
            assert self._brokers(outbox_repo, message_id) == ["default"]

    def test_an_existing_external_row_is_not_created_again(self, tmp_path):
        domain = self._domain(tmp_path, "ext-a", "ext-b")
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain)
            for row in outbox_repo.find_all_by_message_id(message_id):
                if row.target_broker != "ext-a":
                    outbox_repo._dao.delete(row)

            assert reconcile_outbox(domain) == 2
            assert self._brokers(outbox_repo, message_id) == [
                "default",
                "ext-a",
                "ext-b",
            ]

    def test_a_second_run_creates_nothing(self, tmp_path):
        domain = self._domain(tmp_path, "ext-a")
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            message_id = self._credit(domain)
            outbox_repo._dao._delete_all()

            assert reconcile_outbox(domain) == 2
            assert reconcile_outbox(domain) == 0
            assert self._brokers(outbox_repo, message_id) == ["default", "ext-a"]

    def test_lost_rows_behind_a_later_commit_get_every_broker_back(self, tmp_path):
        domain = self._domain(tmp_path, "ext-a")
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            older_id = self._credit(domain)
            newer_id = self._credit(domain)
            _lose_rows(outbox_repo, older_id)

            assert reconcile_outbox(domain) == 2
            assert self._brokers(outbox_repo, older_id) == ["default", "ext-a"]
            assert self._brokers(outbox_repo, newer_id) == ["default", "ext-a"]


@pytest.mark.no_test_domain
class TestReconcileSkipsRowsCleanupMayHaveDeleted:
    """Cleanup deletes delivered rows after ``published_retention_hours`` and
    abandoned rows after ``abandoned_retention_hours``. A deleted row looks the
    same as one lost in a crash, so reconcile must not rebuild it and send the
    event again."""

    def _domain(self, tmp_path, **cleanup):
        def configure(domain):
            _with_external_brokers("ext-a")(domain)
            domain.config["outbox"]["cleanup"].update(cleanup)

        domain = _make_domain_with(
            tmp_path,
            (Credited, {"part_of": Wallet, "published": True}),
            before_init=configure,
        )
        domain.clock = FrozenClock(datetime.now(UTC))
        return domain

    def _credit_and_lose_rows(self, domain):
        outbox_repo = _create_tables(domain)
        wallet = Wallet()
        wallet.raise_(Credited(wallet_id=wallet.id, amount=100))
        domain.repository_for(Wallet).add(wallet)
        message_id = _newest_message_id(domain)
        assert len(outbox_repo.find_all_by_message_id(message_id)) == 2
        outbox_repo._dao._delete_all()
        return outbox_repo, message_id

    def test_event_older_than_the_published_retention_is_not_rebuilt(self, tmp_path):
        domain = self._domain(tmp_path)
        with domain.domain_context():
            outbox_repo, message_id = self._credit_and_lose_rows(domain)
            domain.clock.advance(timedelta(hours=169))

            assert reconcile_outbox(domain) == 0
            assert outbox_repo.find_all_by_message_id(message_id) == []

    def test_event_inside_the_published_retention_is_rebuilt(self, tmp_path):
        domain = self._domain(tmp_path)
        with domain.domain_context():
            outbox_repo, message_id = self._credit_and_lose_rows(domain)
            domain.clock.advance(timedelta(hours=167))

            assert reconcile_outbox(domain) == 2
            assert len(outbox_repo.find_all_by_message_id(message_id)) == 2

    def test_the_shorter_retention_decides(self, tmp_path):
        domain = self._domain(
            tmp_path, published_retention_hours=500, abandoned_retention_hours=24
        )
        with domain.domain_context():
            outbox_repo, message_id = self._credit_and_lose_rows(domain)
            domain.clock.advance(timedelta(hours=25))

            assert reconcile_outbox(domain) == 0
            assert outbox_repo.find_all_by_message_id(message_id) == []

    def test_only_events_inside_the_retention_are_rebuilt(self, tmp_path):
        domain = self._domain(tmp_path)
        with domain.domain_context():
            outbox_repo, old_id = self._credit_and_lose_rows(domain)
            domain.clock.advance(timedelta(hours=169))
            _, new_id = self._credit_and_lose_rows(domain)

            assert reconcile_outbox(domain) == 2
            assert outbox_repo.find_all_by_message_id(old_id) == []
            assert len(outbox_repo.find_all_by_message_id(new_id)) == 2

    def test_old_rowless_event_behind_a_recent_commit_is_not_rebuilt(self, tmp_path):
        """With every event in the window checked, the cutoff alone keeps a row
        that cleanup deleted from being rebuilt and sent again."""
        domain = self._domain(tmp_path)
        with domain.domain_context():
            outbox_repo, old_id = self._credit_and_lose_rows(domain)
            domain.clock.advance(timedelta(hours=169))
            wallet = Wallet()
            wallet.raise_(Credited(wallet_id=wallet.id, amount=100))
            domain.repository_for(Wallet).add(wallet)
            new_id = _newest_message_id(domain)

            assert reconcile_outbox(domain) == 0
            assert outbox_repo.find_all_by_message_id(old_id) == []
            assert len(outbox_repo.find_all_by_message_id(new_id)) == 2

    def test_message_without_a_stored_time_is_not_recent(self):
        cutoff = datetime.now(UTC)
        message = Message(
            data={}, metadata=Metadata(headers=MessageHeaders(id="m-1", time=None))
        )
        assert _written_after(message, cutoff) is False
        old = Message(
            data={},
            metadata=Metadata(
                headers=MessageHeaders(id="m-2", time=cutoff - timedelta(seconds=1))
            ),
        )
        assert _written_after(old, cutoff) is False


@pytest.mark.no_test_domain
class TestReconcileSkipsStateBasedAggregates:
    """A state-based aggregate's row commits or rolls back with its outbox rows,
    so its event with no outbox row has no saved change behind it. Reconcile
    rebuilds rows only for event-sourced aggregates, whose event store is their
    state."""

    def test_event_of_an_aggregate_that_was_never_saved_is_not_repaired(
        self, domain_and_repo
    ):
        """The state a failed relational commit leaves: the event is in the
        store, and neither the account row nor its outbox row is."""
        domain, outbox_repo = domain_and_repo
        account = Account(balance=100)
        account.raise_(Deposited(account_id=account.id, amount=100))
        domain.event_store.store.append(account._events[0])
        assert _newest_message_id(domain) == account._events[0]._metadata.headers.id

        assert reconcile_outbox(domain) == 0
        assert outbox_repo._dao.query.all().items == []
        assert domain.repository_for(Account)._dao.query.all().items == []

    def test_event_of_a_saved_aggregate_with_no_outbox_row_is_not_repaired(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        account = _deposit(domain)
        last = domain.event_store.store.read_last_message("$all")
        message_id = last.metadata.headers.id
        outbox_repo._dao._delete_all()

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(message_id) == []
        saved = domain.repository_for(Account).get(account.id)
        assert saved.balance == 100
        # ``sequence_id`` is ``<aggregate version>.<event number>``.
        event_version = int(last.metadata.domain.sequence_id.split(".")[0])
        assert saved._version == event_version

    def test_published_event_of_a_state_based_aggregate_gets_no_broker_rows(
        self, tmp_path
    ):
        domain = _make_domain_with(
            tmp_path,
            (Audited, {"part_of": Account, "published": True}),
            before_init=_with_external_brokers("ext-a", "ext-b"),
        )
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            account = Account(balance=100)
            account.raise_(Audited(account_id=account.id))
            domain.event_store.store.append(account._events[0])
            message_id = account._events[0]._metadata.headers.id

            assert reconcile_outbox(domain) == 0
            assert outbox_repo.find_all_by_message_id(message_id) == []
            assert outbox_repo._dao.query.all().items == []

    def test_event_sourced_event_is_rebuilt_as_pending_without_its_aggregate(
        self, domain_and_repo, monkeypatch
    ):
        """Reconcile rebuilds the row from the stored event alone and never
        loads the wallet, through its repository or from the event store."""
        domain, outbox_repo = domain_and_repo
        wallet = Wallet()
        wallet.raise_(Funded(wallet_id=wallet.id, amount=100))
        domain.event_store.store.append(wallet._events[0])
        message_id = wallet._events[0]._metadata.headers.id
        # The wallet can be loaded, so a lookup would succeed if reconcile made one.
        assert domain.repository_for(Wallet).get(wallet.id).balance == 100

        lookups = []
        real_repository_for = domain.repository_for
        real_load_aggregate = domain.event_store.store.load_aggregate

        # The memory event store and the outbox reach their own tables through
        # ``repository_for`` too, so only a wallet lookup counts.
        def repository_for_spy(element_cls):
            if element_cls is Wallet:
                lookups.append(("repository_for", element_cls))
            return real_repository_for(element_cls)

        def load_aggregate_spy(*args, **kwargs):
            lookups.append(("load_aggregate", args))
            return real_load_aggregate(*args, **kwargs)

        monkeypatch.setattr(domain, "repository_for", repository_for_spy)
        monkeypatch.setattr(
            domain.event_store.store, "load_aggregate", load_aggregate_spy
        )

        assert reconcile_outbox(domain) == 1
        assert lookups == []
        [row] = outbox_repo.find_all_by_message_id(message_id)
        assert row.type == Funded.__type__
        assert row.status == OutboxStatus.PENDING.value

    def test_committed_state_based_event_at_the_tail_is_a_noop(self, domain_and_repo):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        _deposit(domain)

        assert reconcile_outbox(domain) == 0
        assert len(outbox_repo._dao.query.all().items) == 2

    def test_state_based_event_at_the_tail_does_not_hide_a_lost_row(
        self, domain_and_repo
    ):
        domain, outbox_repo = domain_and_repo
        _fund(domain)
        [funded_id] = _funded_message_ids(domain)
        outbox_repo._dao._delete_all()
        _deposit(domain)
        deposited_id = _newest_message_id(domain)

        assert reconcile_outbox(domain) == 1
        [row] = outbox_repo.find_all_by_message_id(funded_id)
        assert row.type == Funded.__type__
        assert len(outbox_repo.find_all_by_message_id(deposited_id)) == 1

    def test_provider_without_an_event_sourced_aggregate_reads_nothing(
        self, tmp_path, monkeypatch
    ):
        domain = Domain(name="Reconcile")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{tmp_path / 'reconcile.db'}",
        }
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}
        domain.register(Account)
        domain.register(Deposited, part_of=Account)
        domain.init(traverse=False)
        with domain.domain_context():
            outbox_repo = _create_tables(domain)
            _deposit(domain)
            outbox_repo._dao._delete_all()

            store = domain.event_store.store
            reads = []
            real_read_last_message = store.read_last_message

            def spy(*args, **kwargs):
                reads.append(args)
                return real_read_last_message(*args, **kwargs)

            monkeypatch.setattr(store, "read_last_message", spy)

            assert reconcile_outbox(domain) == 0
            assert reads == []
            assert outbox_repo._dao.query.all().items == []

    def test_provider_with_only_state_based_aggregates_reads_nothing(
        self, tmp_path, monkeypatch
    ):
        """The event-sourced ``Wallet`` is on ``default``, so reconciling
        ``analytics``, where only a state-based aggregate lives, reads nothing."""

        # Local classes, so registering them state-based leaves the module's
        # event-sourced ``Report`` untouched.
        class Note(BaseAggregate):
            title = String(default="")

        class NoteAdded(BaseEvent):
            note_id = Identifier(required=True)

        def add_analytics_database(domain):
            domain.config["databases"]["analytics"] = {
                "provider": "sqlite",
                "database_uri": f"sqlite:///{tmp_path / 'analytics.db'}",
            }

        domain = _make_domain_with(
            tmp_path,
            (Note, {"provider": "analytics"}),
            (NoteAdded, {"part_of": Note}),
            before_init=add_analytics_database,
        )
        with domain.domain_context():
            _create_tables(domain)
            provider = domain.providers["analytics"]
            domain.repository_for(Note)._dao
            analytics_repo = domain._get_outbox_repo("analytics")
            analytics_repo._dao
            provider._metadata.create_all(provider._engine)
            note = Note(title="Q3")
            note.raise_(NoteAdded(note_id=note.id))
            domain.repository_for(Note).add(note)
            assert len(analytics_repo._dao.query.all().items) == 1
            analytics_repo._dao._delete_all()

            store = domain.event_store.store
            reads = []
            real_read_last_message = store.read_last_message

            def spy(*args, **kwargs):
                reads.append(args)
                return real_read_last_message(*args, **kwargs)

            monkeypatch.setattr(store, "read_last_message", spy)

            assert reconcile_outbox(domain, provider_name="analytics") == 0
            assert reads == []
            assert analytics_repo._dao.query.all().items == []
