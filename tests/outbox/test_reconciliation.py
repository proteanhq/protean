"""Reconciliation of the ADR-0015 crash window: events durable in the event
store whose relational outbox row did not land."""

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
from protean.utils.mixins import handle
from protean.utils.outbox import reconcile_outbox
from tests.shared import MESSAGE_DB_URI


class Account(BaseAggregate):
    balance = Integer(default=0)


class Deposited(BaseEvent):
    account_id = Identifier(required=True)
    amount = Integer(required=True)


class Deposit(BaseCommand):
    account_id = Identifier(required=True)
    amount = Integer(required=True)


class DepositHandler(BaseCommandHandler):
    @handle(Deposit)
    def deposit(self, command):
        pass


class AccountBalanceHandler(BaseEventHandler):
    """Opts the Account stream into per-key sequential routing on ``account_id``."""

    @handle(Deposited)
    def on_deposited(self, event):
        pass


class Order(BaseAggregate):
    customer_id = String(max_length=50)


class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    customer_id = String(max_length=50)


class OrderPM(BaseProcessManager):
    order_id = String(max_length=50)

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_placed(self, event):
        self.order_id = event.order_id


class Withdrawn(BaseEvent):
    """Current version: v2 added ``reason``."""

    __version__ = 2
    account_id = Identifier(required=True)
    amount = Integer(required=True)
    reason = String(required=True)


class UpcastWithdrawnV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["reason"] = "unspecified"
        return data


class Report(BaseAggregate):
    """An aggregate persisted by a second provider, so its outbox rows go to that
    provider's outbox table."""

    title = String(max_length=50)


class ReportFiled(BaseEvent):
    report_id = Identifier(required=True)
    title = String(max_length=50)


class Ledger(BaseAggregate):
    """A second bounded context's aggregate, used to write foreign events into a
    shared event store."""

    total = Integer(default=0)


class Posted(BaseEvent):
    ledger_id = Identifier(required=True)
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
        # The Account stream has no ``sequential_by`` handler, so no key.
        assert rows[0].partition_key is None

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


def _make_ownership_domain(tmp_path, *, sequential_by=False, with_pm=False):
    """A domain wired for the ownership tests: Account/Deposited plus the command,
    and optionally a ``sequential_by`` handler or a process manager."""
    db_path = tmp_path / "reconcile_ownership.db"
    domain = Domain(name="ReconcileOwnership")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{db_path}",
    }
    domain.config["enable_outbox"] = True
    domain.config["server"] = {"default_subscription_type": "stream"}
    domain.config["command_processing"] = "async"
    domain.register(Account)
    domain.register(Deposited, part_of=Account)
    domain.register(Deposit, part_of=Account)
    domain.register(DepositHandler, part_of=Account)
    if sequential_by:
        domain.register(
            AccountBalanceHandler, part_of=Account, sequential_by="account_id"
        )
    if with_pm:
        domain.register(Order)
        domain.register(OrderPlaced, part_of=Order)
        domain.register(OrderPM, stream_categories=[Order.meta_.stream_category])
    domain.init(traverse=False)
    return domain


def _make_other_domain(tmp_path):
    """A second bounded context pointed at the same Message-DB event store, with no
    outbox of its own. It writes foreign events into the shared ``$all`` stream."""
    db_path = tmp_path / "other_context.db"
    domain = Domain(name="OtherContext")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{db_path}",
    }
    domain.config["event_store"] = {
        "provider": "message_db",
        "database_uri": MESSAGE_DB_URI,
    }
    domain.register(Ledger)
    domain.register(Posted, part_of=Ledger)
    domain.init(traverse=False)
    return domain


def _post(domain):
    ledger = Ledger(total=10)
    ledger.raise_(Posted(ledger_id=ledger.id, amount=10))
    domain.repository_for(Ledger).add(ledger)
    return ledger


def _prepare_tables(domain, *aggregate_classes):
    """Register the aggregate and outbox tables and create them. Call inside the
    domain context. Returns the default-provider outbox repository."""
    provider = domain.providers["default"]
    for aggregate_cls in aggregate_classes:
        domain.repository_for(aggregate_cls)._dao
    domain._get_outbox_repo("default")._dao
    provider._metadata.create_all(provider._engine)
    return domain._get_outbox_repo("default")


@pytest.mark.no_test_domain
class TestOutboxReconciliationOwnership:
    """Reconcile repairs only the events this domain writes outbox rows for, so a
    command, a foreign event, or a process-manager transition in ``$all`` is
    never copied into the outbox."""

    def test_reconcile_skips_a_command_and_repairs_only_the_event(self, tmp_path):
        domain = _make_ownership_domain(tmp_path)
        with domain.domain_context():
            outbox_repo = _prepare_tables(domain, Account)

            account = _deposit(domain)  # owned event, gets its row
            event_id = _newest_message_id(domain)
            outbox_repo._dao._delete_all()  # crash window: the event's row is gone

            # A command is the newest write in $all. Commands never get outbox rows.
            domain.process(Deposit(account_id=account.id, amount=50))
            command_id = _newest_message_id(domain)
            assert command_id != event_id

            # Reconcile repairs the event and leaves the command alone.
            assert reconcile_outbox(domain) == 1
            assert len(outbox_repo.find_all_by_message_id(event_id)) == 1
            assert outbox_repo.find_all_by_message_id(command_id) == []

    def test_reconcile_repairs_every_owned_event_interleaved_with_commands(
        self, tmp_path
    ):
        """Two owned events lost their rows, with a command between them and a
        command after them. Reconcile rebuilds both events and neither command."""
        domain = _make_ownership_domain(tmp_path)
        with domain.domain_context():
            outbox_repo = _prepare_tables(domain, Account)

            first = _deposit(domain)
            first_id = _newest_message_id(domain)
            domain.process(Deposit(account_id=first.id, amount=1))
            first_command_id = _newest_message_id(domain)
            second = _deposit(domain)
            second_id = _newest_message_id(domain)
            domain.process(Deposit(account_id=second.id, amount=2))
            second_command_id = _newest_message_id(domain)
            outbox_repo._dao._delete_all()  # crash window: both event rows lost

            assert reconcile_outbox(domain) == 2
            assert len(outbox_repo.find_all_by_message_id(first_id)) == 1
            assert len(outbox_repo.find_all_by_message_id(second_id)) == 1
            assert outbox_repo.find_all_by_message_id(first_command_id) == []
            assert outbox_repo.find_all_by_message_id(second_command_id) == []

    def test_reconcile_noop_when_only_a_command_follows_a_repaired_tail(self, tmp_path):
        """When the newest owned event already has its row and a command is the
        newest write, reconcile finds nothing to repair and adds no row."""
        domain = _make_ownership_domain(tmp_path)
        with domain.domain_context():
            outbox_repo = _prepare_tables(domain, Account)

            account = _deposit(domain)  # owned event keeps its row
            domain.process(Deposit(account_id=account.id, amount=50))
            command_id = _newest_message_id(domain)

            assert reconcile_outbox(domain) == 0
            assert outbox_repo.find_all_by_message_id(command_id) == []

    def test_reconcile_skips_an_unregistered_foreign_type(self, tmp_path):
        """A message whose type does not resolve in this domain's registry (as a
        foreign domain's event would not) is skipped."""
        domain = _make_ownership_domain(tmp_path)
        with domain.domain_context():
            outbox_repo = _prepare_tables(domain, Account)

            _deposit(domain)
            message_id = _newest_message_id(domain)
            outbox_repo._dao._delete_all()  # crash window

            # Make the only stored message unresolvable, standing in for an event
            # written by another domain that shares this event store.
            domain._events_and_commands.pop(Deposited.__type__)

            assert reconcile_outbox(domain) == 0
            assert outbox_repo.find_all_by_message_id(message_id) == []

    def test_reconcile_skips_a_process_manager_transition_event(self, tmp_path):
        domain = _make_ownership_domain(tmp_path, with_pm=True)
        with domain.domain_context():
            outbox_repo = _prepare_tables(domain, Account, Order)

            _deposit(domain)  # owned event keeps its row

            # A PM transition is appended directly to the store with no outbox row.
            OrderPM._handle(OrderPlaced(order_id="ORD-1", customer_id="CUST-1"))
            transition_id = _newest_message_id(domain)

            assert reconcile_outbox(domain) == 0
            assert outbox_repo.find_all_by_message_id(transition_id) == []

    def test_reconcile_leaves_another_providers_events_to_that_provider(self, tmp_path):
        """Each provider has its own outbox. Reconciling the default outbox must
        not copy an event whose aggregate is persisted by another provider."""
        domain = Domain(name="ReconcileProviders")
        for name in ("default", "analytics"):
            domain.config["databases"][name] = {
                "provider": "sqlite",
                "database_uri": f"sqlite:///{tmp_path / f'{name}.db'}",
            }
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}
        domain.register(Account)
        domain.register(Deposited, part_of=Account)
        domain.register(Report, provider="analytics")
        domain.register(ReportFiled, part_of=Report)
        domain.init(traverse=False)

        with domain.domain_context():
            default_outbox = _prepare_tables(domain, Account)
            analytics = domain.providers["analytics"]
            domain.repository_for(Report)._dao
            analytics_outbox = domain._get_outbox_repo("analytics")
            analytics_outbox._dao
            analytics._metadata.create_all(analytics._engine)

            _deposit(domain)
            deposit_id = _newest_message_id(domain)
            report = Report(title="Q3")
            report.raise_(ReportFiled(report_id=report.id, title="Q3"))
            domain.repository_for(Report).add(report)
            report_event_id = _newest_message_id(domain)
            assert len(analytics_outbox.find_all_by_message_id(report_event_id)) == 1

            default_outbox._dao._delete_all()  # the default outbox lost its row

            assert reconcile_outbox(domain, provider_name="default") == 1
            assert len(default_outbox.find_all_by_message_id(deposit_id)) == 1
            assert default_outbox.find_all_by_message_id(report_event_id) == []

    def test_reconcile_repairs_fact_events(self, tmp_path):
        """Fact events are raised on the aggregate and get outbox rows, so
        reconcile rebuilds them alongside the domain event."""
        domain = Domain(name="ReconcileFacts")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{tmp_path / 'facts.db'}",
        }
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}
        domain.register(Account, fact_events=True)
        domain.register(Deposited, part_of=Account)
        domain.init(traverse=False)

        with domain.domain_context():
            outbox_repo = _prepare_tables(domain, Account)
            _deposit(domain)
            written = {row.message_id for row in outbox_repo.find_unprocessed()}
            assert len(written) == 2  # the domain event and its fact event

            outbox_repo._dao._delete_all()  # crash window

            assert reconcile_outbox(domain) == 2
            rebuilt = {row.message_id for row in outbox_repo.find_unprocessed()}
            assert rebuilt == written

    def test_reconcile_repairs_an_owned_event_stored_under_an_old_version(
        self, tmp_path
    ):
        """After a version bump the registry holds only the current type. An
        owned event stored as v1 still resolves through the upcaster chain, and
        its rebuilt row keeps the partition key of the upcast event."""
        domain = Domain(name="ReconcileVersions")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{tmp_path / 'versions.db'}",
        }
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}
        domain.register(Account)
        domain.register(Deposited, part_of=Account)
        domain.register(Withdrawn, part_of=Account)
        domain.register(
            AccountBalanceHandler, part_of=Account, sequential_by="account_id"
        )
        domain.upcaster(
            UpcastWithdrawnV1ToV2, event_type=Withdrawn, from_version=1, to_version=2
        )
        domain.init(traverse=False)

        with domain.domain_context():
            outbox_repo = _prepare_tables(domain, Account)
            category = Account.meta_.stream_category
            old_type = "ReconcileVersions.Withdrawn.v1"
            assert old_type not in domain._events_and_commands

            # A v1 event durable in the store whose outbox row never landed.
            domain.event_store.store._write(
                f"{category}-acct-1",
                old_type,
                {"account_id": "acct-1", "amount": 5},
                {
                    "headers": {
                        "id": "withdrawn-v1",
                        "type": old_type,
                        "time": "2025-01-01T00:00:00+00:00",
                        "stream": f"{category}-acct-1",
                    },
                    "envelope": {"specversion": "1.0"},
                    "domain": {
                        "fqn": "tests.outbox.test_reconciliation.Withdrawn",
                        "kind": "EVENT",
                        "stream_category": category,
                        "version": 1,
                        "sequence_id": "0",
                        "asynchronous": True,
                    },
                },
            )

            assert reconcile_outbox(domain) == 1
            rows = outbox_repo.find_all_by_message_id("withdrawn-v1")
            assert len(rows) == 1
            assert rows[0].type == old_type
            assert rows[0].partition_key == "acct-1"

    def test_reconcile_preserves_the_partition_key(self, tmp_path):
        domain = _make_ownership_domain(tmp_path, sequential_by=True)
        with domain.domain_context():
            outbox_repo = _prepare_tables(domain, Account)
            assert domain._partition_keys  # precondition: the stream is partitioned

            _deposit(domain)
            message_id = _newest_message_id(domain)
            rows = outbox_repo.find_all_by_message_id(message_id)
            assert len(rows) == 1
            original_key = rows[0].partition_key
            assert original_key is not None  # the key the unit of work wrote

            outbox_repo._dao._delete_all()  # crash window

            assert reconcile_outbox(domain) == 1
            rebuilt = outbox_repo.find_all_by_message_id(message_id)
            assert len(rebuilt) == 1
            assert rebuilt[0].partition_key == original_key


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

    def _write_foreign_event(self, tmp_path):
        """Write another context's event into the shared store and return its id."""
        other = _make_other_domain(tmp_path)
        with other.domain_context():
            provider = other.providers["default"]
            other.repository_for(Ledger)._dao
            provider._metadata.create_all(provider._engine)
            _post(other)
            posted_id = _newest_message_id(other)
        other.event_store.store.close()
        return posted_id

    def test_reconcile_ignores_a_foreign_domains_event(self, domain_and_repo, tmp_path):
        """Domains A and B share one store. When B's event is newest in ``$all``
        and A's own event still has its row, reconcile(A) returns 0 and adds no
        row for B's event."""
        domain, outbox_repo = domain_and_repo
        _deposit(domain)  # A's event keeps its row
        event_id = _newest_message_id(domain)

        posted_id = self._write_foreign_event(tmp_path)  # B's event, now newest
        assert posted_id != event_id

        assert reconcile_outbox(domain) == 0
        assert outbox_repo.find_all_by_message_id(posted_id) == []

    def test_reconcile_repairs_only_the_owning_domains_event(
        self, domain_and_repo, tmp_path
    ):
        """With A's row lost in the crash and B's event newest in ``$all``,
        reconcile(A) rebuilds A's row only and leaves B's event untouched."""
        domain, outbox_repo = domain_and_repo
        _deposit(domain)
        event_id = _newest_message_id(domain)
        outbox_repo._dao._delete_all()  # A's row lost in the crash window

        posted_id = self._write_foreign_event(tmp_path)  # B's event, now newest
        assert posted_id != event_id

        assert reconcile_outbox(domain) == 1
        assert len(outbox_repo.find_all_by_message_id(event_id)) == 1
        assert outbox_repo.find_all_by_message_id(posted_id) == []
