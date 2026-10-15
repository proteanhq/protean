"""Tests for the Event Sourcing tutorial source files (ch01-ch22).

Each test loads the chapter module from ``docs_src`` with ``load_example`` and
exercises its domain objects, commands, and assertions, the same logic as the
chapter's ``if __name__ == "__main__"`` block.

Runs with in-memory adapters by default.  Pass ``--db``, ``--store``,
and ``--broker`` to pytest to exercise real adapters (same flags used
by the rest of the test suite).
"""

import types
from datetime import UTC, datetime

import pytest

from protean.exceptions import ObjectNotFoundError, ValidationError
from tests.docs.support import load_example, outcome_counts, run_example_tests

# Load all 22 chapters at module level (each has its own Domain instance).
# ``load_example`` runs a chapter afresh on every call, so load each one once.
ch01 = load_example("guides/getting-started/es-tutorial/ch01.py")
ch02 = load_example("guides/getting-started/es-tutorial/ch02.py")
ch03 = load_example("guides/getting-started/es-tutorial/ch03.py")
ch04 = load_example("guides/getting-started/es-tutorial/ch04.py")
ch05 = load_example("guides/getting-started/es-tutorial/ch05.py")
ch06 = load_example("guides/getting-started/es-tutorial/ch06.py")
ch07 = load_example("guides/getting-started/es-tutorial/ch07.py")
ch08 = load_example("guides/getting-started/es-tutorial/ch08.py")
ch09 = load_example("guides/getting-started/es-tutorial/ch09.py")
ch10 = load_example("guides/getting-started/es-tutorial/ch10.py")
ch11 = load_example("guides/getting-started/es-tutorial/ch11.py")
ch11_v3 = load_example("guides/getting-started/es-tutorial/ch11_v3.py")
ch12 = load_example("guides/getting-started/es-tutorial/ch12.py")
ch13 = load_example("guides/getting-started/es-tutorial/ch13.py")
ch14 = load_example("guides/getting-started/es-tutorial/ch14.py")
ch15 = load_example("guides/getting-started/es-tutorial/ch15.py")
ch16 = load_example("guides/getting-started/es-tutorial/ch16.py")
ch17 = load_example("guides/getting-started/es-tutorial/ch17.py")
ch18 = load_example("guides/getting-started/es-tutorial/ch18.py")
ch19 = load_example("guides/getting-started/es-tutorial/ch19.py")
ch20 = load_example("guides/getting-started/es-tutorial/ch20.py")
ch21 = load_example("guides/getting-started/es-tutorial/ch21.py")
ch22 = load_example("guides/getting-started/es-tutorial/ch22.py")

# Chapters that don't call domain.init() at module level
_NEEDS_INIT = {ch05, ch08, ch17, ch18, ch21}

# Chapters that have projections (need DB artifact create/drop with real DBs)
_HAS_PROJECTIONS = {ch06, ch08, ch15, ch18, ch20, ch22}


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------
def _cleanup(domain) -> None:
    """Reset all stores and close connections after a test."""
    for provider_name in domain.providers:
        provider = domain.providers[provider_name]
        try:
            provider._data_reset()
        finally:
            provider.close()

    if domain.event_store.store:
        try:
            domain.event_store.store._data_reset()
        finally:
            domain.event_store.store.close()


def _init_if_needed(mod) -> None:
    """Call domain.init() for chapters that skip it at module level."""
    if mod in _NEEDS_INIT:
        mod.domain.init(traverse=False)
        mod.domain.config["event_processing"] = "sync"
        mod.domain.config["command_processing"] = "sync"


def _configure_domain(
    domain, db_config: dict, store_config: dict, broker_config: dict
) -> None:
    """Reconfigure a chapter domain with the session adapter configs.

    Same pattern as the ``test_domain`` fixture in conftest.py:
    overwrite config keys and call ``_initialize()`` to reconnect adapters.
    """
    domain.config["databases"]["default"] = db_config
    domain.config["event_store"] = store_config
    domain.config["brokers"]["default"] = broker_config
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"
    domain.config["message_processing"] = "sync"
    domain._initialize()


class _ESTutorialBase:
    """Base class providing autouse adapter configuration for all ES tutorial tests.

    Each subclass sets ``_chapter_mod`` to its chapter module.  The fixture
    reconfigures the chapter's domain with the session-scoped adapter configs
    (db_config / store_config / broker_config) from conftest.py — the same
    ones used by the ``test_domain`` fixture.
    """

    _chapter_mod: types.ModuleType  # set by each subclass

    @pytest.fixture(autouse=True)
    def _configure_chapter(self, db_config, store_config, broker_config):
        mod = self._chapter_mod
        _init_if_needed(mod)
        domain = mod.domain
        _configure_domain(domain, db_config, store_config, broker_config)

        has_projections = mod in _HAS_PROJECTIONS
        if has_projections:
            domain.providers["default"]._create_database_artifacts()

        yield domain

        if has_projections:
            domain.providers["default"]._drop_database_artifacts()

        _cleanup(domain)


# ---------------------------------------------------------------------------
# PART I: Building the Foundation (Ch 1-5)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestESTutorialCh01(_ESTutorialBase):
    _chapter_mod = ch01

    def test_faithful_ledger(self):
        """Ch1: Create ES aggregate, persist, retrieve via event replay."""
        domain = ch01.domain
        with domain.domain_context():
            account = ch01.Account.open("ACC-001", "Alice Johnson", 1000.00)
            repo = domain.repository_for(ch01.Account)
            repo.add(account)

            loaded = repo.get(account.id)
            assert loaded.holder_name == "Alice Johnson"
            assert loaded.balance == 1000.00
            assert loaded.status == "ACTIVE"


@pytest.mark.no_test_domain
class TestESTutorialCh02(_ESTutorialBase):
    _chapter_mod = ch02

    def test_deposits_and_withdrawals(self):
        """Ch2: Multiple events, version tracking, input validation."""
        domain = ch02.domain
        with domain.domain_context():
            account = ch02.Account.open("ACC-001", "Alice Johnson", 1000.00)
            account.deposit(500.00, reference="paycheck")
            account.deposit(200.00, reference="refund")
            account.withdraw(150.00, reference="groceries")

            repo = domain.repository_for(ch02.Account)
            repo.add(account)

            loaded = repo.get(account.id)
            assert loaded.balance == 1550.00
            assert loaded._version == 3

            with pytest.raises(ValidationError):
                loaded.withdraw(10000.00)


@pytest.mark.no_test_domain
class TestESTutorialCh03(_ESTutorialBase):
    _chapter_mod = ch03

    def test_commands_and_pipeline(self):
        """Ch3: Commands, command handler, domain.process()."""
        domain = ch03.domain
        with domain.domain_context():
            account_id = domain.process(
                ch03.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(
                ch03.MakeDeposit(
                    account_id=account_id, amount=500.00, reference="paycheck"
                )
            )
            domain.process(
                ch03.MakeWithdrawal(
                    account_id=account_id, amount=150.00, reference="groceries"
                )
            )

            account = domain.repository_for(ch03.Account).get(account_id)
            assert account.balance == 1350.00


@pytest.mark.no_test_domain
class TestESTutorialCh04(_ESTutorialBase):
    _chapter_mod = ch04

    def test_business_rules(self):
        """Ch4: Invariants prevent overdrafts and invalid closes."""
        domain = ch04.domain
        with domain.domain_context():
            account_id = domain.process(
                ch04.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=100.00,
                )
            )

            # Overdraft rejected
            with pytest.raises(ValidationError):
                domain.process(
                    ch04.MakeWithdrawal(account_id=account_id, amount=200.00)
                )

            # Close with non-zero balance rejected
            with pytest.raises(ValidationError):
                domain.process(
                    ch04.CloseAccount(account_id=account_id, reason="Customer request")
                )

            # Withdraw all, then close succeeds
            domain.process(ch04.MakeWithdrawal(account_id=account_id, amount=100.00))
            domain.process(
                ch04.CloseAccount(account_id=account_id, reason="Customer request")
            )

            account = domain.repository_for(ch04.Account).get(account_id)
            assert account.status == "CLOSED"
            assert account.balance == 0.0


@pytest.mark.no_test_domain
class TestESTutorialCh05(_ESTutorialBase):
    _chapter_mod = ch05

    @pytest.fixture(autouse=True)
    def _reset_event_store_between_tests(self, _configure_chapter):
        """Reset the event store before each test to avoid stream version conflicts.

        Ch05's tests all use the same account_id="acc-123".
        """
        domain = _configure_chapter
        if domain.event_store.store:
            domain.event_store.store._data_reset()

    def _make_account_opened(self):
        return ch05.AccountOpened(
            account_id="acc-123",
            account_number="ACC-001",
            holder_name="Alice Johnson",
            opening_deposit=1000.00,
        )

    def test_open_account(self):
        """Ch5: given().process() for account creation."""
        with ch05.domain.domain_context():
            ch05.test_open_account()

    def test_deposit_increases_balance(self):
        """Ch5: given(events).process() for deposits."""
        with ch05.domain.domain_context():
            ch05.test_deposit_increases_balance(self._make_account_opened())

    def test_overdraft_is_rejected(self):
        """Ch5: Overdraft caught by invariant via testing DSL."""
        with ch05.domain.domain_context():
            ch05.test_overdraft_is_rejected(self._make_account_opened())

    def test_full_account_lifecycle(self):
        """Ch5: Multi-command chaining with .process().process()."""
        with ch05.domain.domain_context():
            ch05.test_full_account_lifecycle(self._make_account_opened())

    def test_cannot_close_with_balance(self):
        """Ch5: Rejection when closing account with non-zero balance."""
        funded = [
            self._make_account_opened(),
            ch05.DepositMade(account_id="acc-123", amount=500.00, reference="paycheck"),
            ch05.DepositMade(account_id="acc-123", amount=200.00, reference="refund"),
        ]
        with ch05.domain.domain_context():
            ch05.test_cannot_close_with_balance(funded)


class TestESTutorialCh05UnderPytest:
    """Ch5: the chapter's conftest and fixtures drive its tests under pytest."""

    def test_the_chapter_file_passes_under_pytest(self):
        result = run_example_tests("guides/getting-started/es-tutorial/ch05.py")
        assert result.returncode == 0, result.stdout + result.stderr
        assert outcome_counts(result) == {"passed": 5}


# ---------------------------------------------------------------------------
# PART II: Growing the Platform (Ch 6-10)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestESTutorialCh06(_ESTutorialBase):
    _chapter_mod = ch06

    def test_account_dashboard(self):
        """Ch6: Projection and projector maintain read model."""
        domain = ch06.domain
        with domain.domain_context():
            account_id = domain.process(
                ch06.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(
                ch06.MakeDeposit(
                    account_id=account_id, amount=500.00, reference="paycheck"
                )
            )

            summary = domain.repository_for(ch06.AccountSummary).get(account_id)
            assert summary.balance == 1500.00
            assert summary.transaction_count == 2


@pytest.mark.no_test_domain
class TestESTutorialCh07(_ESTutorialBase):
    _chapter_mod = ch07

    def test_reacting_to_events(self):
        """Ch7: Event handlers fire for compliance and notifications."""
        domain = ch07.domain
        with domain.domain_context():
            account_id = domain.process(
                ch07.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=500.00,
                )
            )
            domain.process(
                ch07.MakeDeposit(
                    account_id=account_id,
                    amount=15000.00,
                    reference="wire transfer",
                )
            )
            domain.process(
                ch07.MakeWithdrawal(
                    account_id=account_id,
                    amount=6000.00,
                    reference="property payment",
                )
            )

            account = domain.repository_for(ch07.Account).get(account_id)
            assert account.balance == 9500.00


@pytest.mark.no_test_domain
class TestESTutorialCh08(_ESTutorialBase):
    _chapter_mod = ch08

    def test_going_async(self):
        """Ch8: Domain initializes with all elements for async server."""
        domain = ch08.domain
        with domain.domain_context():
            # Verify domain elements are registered
            assert len(domain.registry.aggregates) > 0
            assert len(domain.registry.commands) > 0
            assert len(domain.registry.events) > 0

            # Process a command to verify the pipeline works
            account_id = domain.process(
                ch08.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(
                ch08.MakeDeposit(account_id=account_id, amount=500.00, reference="test")
            )

            account = domain.repository_for(ch08.Account).get(account_id)
            assert account.balance == 1500.00

            # Projection is maintained in sync mode
            summary = domain.repository_for(ch08.AccountSummary).get(account_id)
            assert summary.balance == 1500.00
            assert summary.transaction_count == 2

    def test_async_deposit_is_queued_and_not_handled(self):
        """Ch8: with async processing, the deposit command waits in its stream."""
        domain = ch08.domain
        with domain.domain_context():
            account_id = domain.process(
                ch08.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.config["command_processing"] = "async"
            try:
                ch08.queue_deposit(account_id)
            finally:
                domain.config["command_processing"] = "sync"

            account = domain.repository_for(ch08.Account).get(account_id)
            assert account.balance == 1000.00

            category = f"{ch08.Account.meta_.stream_category}:command"
            queued = [
                message["data"]
                for message in domain.event_store.store._read(category)
                if message["type"].endswith(".MakeDeposit.v1")
            ]
            assert queued == [
                {"account_id": account_id, "amount": 500.0, "reference": "paycheck"}
            ]


@pytest.mark.no_test_domain
class TestESTutorialCh09(_ESTutorialBase):
    _chapter_mod = ch09

    def test_transferring_funds(self):
        """Ch9: Transfer aggregate + process manager initiation."""
        domain = ch09.domain
        with domain.domain_context():
            alice_id = domain.process(
                ch09.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=10000.00,
                )
            )
            bob_id = domain.process(
                ch09.OpenAccount(
                    account_number="ACC-002",
                    holder_name="Bob Smith",
                    opening_deposit=5000.00,
                )
            )

            transfer_id = domain.process(
                ch09.InitiateTransfer(
                    source_account_id=alice_id,
                    destination_account_id=bob_id,
                    amount=3000.00,
                )
            )

            transfer = domain.repository_for(ch09.Transfer).get(transfer_id)
            assert transfer.status == "INITIATED"


@pytest.mark.no_test_domain
class TestESTutorialCh10(_ESTutorialBase):
    _chapter_mod = ch10

    def test_entities_inside_aggregates(self):
        """Ch10: HasMany entity (AuthorizedSignatory) inside ES aggregate."""
        domain = ch10.domain
        with domain.domain_context():
            account_id = domain.process(
                ch10.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=5000.00,
                )
            )
            domain.process(
                ch10.AddSignatory(
                    account_id=account_id,
                    name="Bob Smith",
                    email="bob@fidelis.com",
                    role="MANAGER",
                )
            )
            domain.process(
                ch10.AddSignatory(
                    account_id=account_id,
                    name="Carol Davis",
                    email="carol@fidelis.com",
                    role="OPERATOR",
                )
            )

            account = domain.repository_for(ch10.Account).get(account_id)
            assert len(account.signatories) == 2
            assert account.signatories[0].name == "Bob Smith"

            # Remove a signatory
            domain.process(
                ch10.RemoveSignatory(account_id=account_id, email="bob@fidelis.com")
            )

            account = domain.repository_for(ch10.Account).get(account_id)
            assert len(account.signatories) == 1
            assert account.signatories[0].name == "Carol Davis"


# ---------------------------------------------------------------------------
# PART III: Evolution and Adaptation (Ch 11-14)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestESTutorialCh11(_ESTutorialBase):
    _chapter_mod = ch11

    def test_event_upcasting(self):
        """Ch11: Upcaster adds source_type to DepositMade v1 events."""
        domain = ch11.domain
        with domain.domain_context():
            account_id = domain.process(
                ch11.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(
                ch11.MakeDeposit(
                    account_id=account_id,
                    amount=500.00,
                    reference="paycheck",
                    source_type="payroll",
                )
            )
            domain.process(
                ch11.MakeDeposit(
                    account_id=account_id,
                    amount=250.00,
                    reference="wire-transfer",
                    source_type="bank_transfer",
                )
            )

            account = domain.repository_for(ch11.Account).get(account_id)
            assert account.balance == 1750.00

            # Verify upcaster metadata
            assert ch11.UpcastDepositV1ToV2.meta_.event_type == ch11.DepositMade
            assert ch11.UpcastDepositV1ToV2.meta_.from_version == 1
            assert ch11.UpcastDepositV1ToV2.meta_.to_version == 2


def _write_old_deposit(domain, account_id: str, version: int, data: dict) -> None:
    """Append a ``DepositMade`` payload stored at an older schema version."""
    event_cls = ch11_v3.DepositMade
    type_string = event_cls.__type__.rsplit(".", 1)[0] + f".v{version}"
    category = ch11_v3.Account.meta_.stream_category
    stream = f"{category}-{account_id}"
    store = domain.event_store.store
    position = len(store._read(stream))
    store._write(
        stream,
        type_string,
        {"account_id": account_id, **data},
        {
            "headers": {
                "id": f"{account_id}-{position}",
                "type": type_string,
                "time": "2025-01-01T00:00:00+00:00",
                "stream": stream,
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "fqn": f"{event_cls.__module__}.{event_cls.__qualname__}",
                "kind": "EVENT",
                "origin_stream": None,
                "stream_category": category,
                "version": version,
                "sequence_id": str(position),
                "asynchronous": True,
            },
        },
        position - 1,
    )


@pytest.mark.no_test_domain
class TestESTutorialCh11ChainedUpcasters(_ESTutorialBase):
    _chapter_mod = ch11_v3

    def _open_account(self, domain) -> str:
        account = ch11_v3.Account.open(holder_name="Alice", opening_deposit=1000.00)
        domain.repository_for(ch11_v3.Account).add(account)
        return str(account.id)

    def test_v1_deposit_passes_through_both_upcasters(self):
        """Ch11: a stored v1 deposit gains source_type and currency on replay."""
        domain = ch11_v3.domain
        with domain.domain_context():
            account_id = self._open_account(domain)
            _write_old_deposit(domain, account_id, 1, {"amount": 50.0})

            account = domain.repository_for(ch11_v3.Account).get(account_id)
            assert account.balance == 1050.00
            assert account.last_source_type == "unknown"
            assert account.currency == "USD"

    def test_each_upcaster_adds_its_field(self):
        """Ch11: each upcaster adds the field its version introduced."""
        assert ch11_v3.UpcastDepositV1ToV2().upcast({"amount": 50.0}) == {
            "amount": 50.0,
            "source_type": "unknown",
        }
        assert ch11_v3.UpcastDepositV2ToV3().upcast(
            {"amount": 50.0, "source_type": "payroll"}
        ) == {"amount": 50.0, "source_type": "payroll", "currency": "USD"}

    def test_a_v1_payload_runs_through_both_upcasters_in_order(self):
        """Ch11: the chain for a v1 deposit applies v1 to v2, then v2 to v3."""
        base_type = ch11_v3.DepositMade.__type__.rsplit(".", 1)[0]

        upcast = ch11_v3.domain._upcaster_chain.upcast(base_type, 1, {"amount": 50.0})

        assert upcast == {"amount": 50.0, "source_type": "unknown", "currency": "USD"}

    def test_v2_deposit_keeps_its_source_and_gains_currency(self):
        """Ch11: a stored v2 deposit only passes through the v2 to v3 upcaster."""
        domain = ch11_v3.domain
        with domain.domain_context():
            account_id = self._open_account(domain)
            _write_old_deposit(
                domain, account_id, 2, {"amount": 75.0, "source_type": "payroll"}
            )

            account = domain.repository_for(ch11_v3.Account).get(account_id)
            assert account.balance == 1075.00
            assert account.last_source_type == "payroll"
            assert account.currency == "USD"

    def test_current_deposit_keeps_its_currency(self):
        """Ch11: a v3 deposit is read as written, with no upcasting."""
        domain = ch11_v3.domain
        with domain.domain_context():
            repo = domain.repository_for(ch11_v3.Account)
            account = ch11_v3.Account.open(holder_name="Bob", opening_deposit=10.00)
            account.deposit(5.00, source_type="cash", currency="EUR")
            repo.add(account)

            account = repo.get(account.id)
            assert account.balance == 15.00
            assert account.currency == "EUR"
            assert account.last_source_type == "cash"


@pytest.mark.no_test_domain
class TestESTutorialCh12(_ESTutorialBase):
    _chapter_mod = ch12

    def test_snapshots(self):
        """Ch12: Snapshot creation and aggregate loading from snapshot."""
        domain = ch12.domain
        with domain.domain_context():
            account_id = domain.process(
                ch12.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            for i in range(1, 8):
                domain.process(
                    ch12.MakeDeposit(
                        account_id=account_id,
                        amount=100.00,
                        reference=f"deposit-{i}",
                    )
                )

            created = domain.create_snapshot(ch12.Account, account_id)
            assert created is True

            account = domain.repository_for(ch12.Account).get(account_id)
            assert account.balance == 1700.00  # 1000 + (7 * 100)

    def test_snapshots_on_demand(self):
        """Ch12: snapshot one account, then every account."""
        domain = ch12.domain
        with domain.domain_context():
            account_ids = [
                domain.process(
                    ch12.OpenAccount(
                        account_number=f"ACC-00{n}",
                        holder_name="Alice Johnson",
                        opening_deposit=1000.00,
                    )
                )
                for n in (1, 2)
            ]
            for account_id in account_ids:
                domain.process(ch12.MakeDeposit(account_id=account_id, amount=100.00))

        assert ch12.snapshot_accounts(account_ids[0]) == (True, 2)

        with domain.domain_context():
            account = domain.repository_for(ch12.Account).get(account_ids[0])
            assert account.balance == 1100.00

    def test_snapshot_of_a_missing_account_fails(self):
        """Ch12: snapshotting an account that does not exist raises."""
        with pytest.raises(ObjectNotFoundError):
            ch12.snapshot_accounts("no-such-account")


@pytest.mark.no_test_domain
class TestESTutorialCh13(_ESTutorialBase):
    _chapter_mod = ch13

    def test_temporal_queries(self, capsys):
        """Ch13: at_version and as_of temporal queries, read-only guard."""
        domain = ch13.domain
        with domain.domain_context():
            account_id = domain.process(
                ch13.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(
                ch13.MakeDeposit(
                    account_id=account_id, amount=500.00, reference="paycheck"
                )
            )
            domain.process(
                ch13.MakeDeposit(
                    account_id=account_id, amount=200.00, reference="refund"
                )
            )

            midpoint = datetime.now(UTC)

            domain.process(
                ch13.MakeWithdrawal(
                    account_id=account_id, amount=500.00, reference="rent"
                )
            )
            domain.process(
                ch13.MakeDeposit(
                    account_id=account_id, amount=300.00, reference="freelance"
                )
            )

            repo = domain.repository_for(ch13.Account)

            # Current state
            current = repo.get(account_id)
            assert current.balance == 1500.00

            # at_version=2 replays events 0, 1, 2 (first 3 events)
            historical = ch13.account_at_version(account_id, 2)
            assert historical.balance == 1700.00

            # as_of midpoint (before rent withdrawal)
            snapshot_in_time = ch13.account_as_of(account_id, midpoint)
            assert snapshot_in_time.balance == 1700.00

            # Temporal aggregates are read-only, and the guard leaves no event
            message = ch13.try_to_change(historical)
            assert message.startswith("Cannot raise events on a temporally-loaded")
            assert historical._events == []

            # The current aggregate is not temporal, so it can change
            assert ch13.try_to_change(current) == ""

        printed = capsys.readouterr().out.splitlines()
        assert "Balance at version 2: $1700.00" in printed
        assert f"Balance on {midpoint:%B %d}: $1700.00" in printed
        assert message in printed


@pytest.mark.no_test_domain
class TestESTutorialCh14(_ESTutorialBase):
    _chapter_mod = ch14

    def test_connecting_outside_world(self):
        """Ch14: Subscriber as ACL, event/command enrichers."""
        domain = ch14.domain
        with domain.domain_context():
            account_id = domain.process(
                ch14.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )

            # Invoke subscriber directly (simulates broker delivery)
            webhook_payload = {
                "id": "pf-txn-42",
                "type": "payment.completed",
                "account_id": account_id,
                "amount": 250.00,
                "reference": "payflow-pf-txn-42",
            }
            subscriber = ch14.PayFlowWebhookSubscriber()
            subscriber(webhook_payload)

            # Verify the deposit was processed
            account = domain.repository_for(ch14.Account).get(account_id)
            assert account.balance == 1250.00

            # Verify enrichers are registered
            assert ch14.add_tenant_context in domain._event_enrichers
            assert ch14.add_request_context in domain._command_enrichers

    def test_audit_handler_reads_the_tenant_from_the_event(self, capsys):
        """Ch14: the event handler sees what the event enricher attached."""
        domain = ch14.domain
        with domain.domain_context():
            account_id = domain.process(
                ch14.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(ch14.MakeDeposit(account_id=account_id, amount=10.00))

        printed = capsys.readouterr().out.splitlines()
        assert printed.count("[Audit] Deposit for tenant fidelis-main") == 1

    def test_handle_error_reports_the_failure(self, capsys):
        """Ch14: the subscriber's error handler prints the error and payload."""
        ch14.PayFlowWebhookSubscriber.handle_error(
            KeyError("account_id"), {"type": "payment.completed"}
        )

        assert capsys.readouterr().out == (
            "[PayFlow] Error processing webhook: 'account_id' | "
            "Payload: {'type': 'payment.completed'}\n"
        )


# ---------------------------------------------------------------------------
# PART IV: Production Operations (Ch 15-19)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestESTutorialCh15(_ESTutorialBase):
    _chapter_mod = ch15

    def test_fact_events(self):
        """Ch15: fact_events=True generates full-state events."""
        domain = ch15.domain
        with domain.domain_context():
            account_id = domain.process(
                ch15.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(
                ch15.MakeDeposit(
                    account_id=account_id, amount=500.00, reference="paycheck"
                )
            )
            domain.process(
                ch15.MakeWithdrawal(
                    account_id=account_id, amount=200.00, reference="groceries"
                )
            )

            account = domain.repository_for(ch15.Account).get(account_id)
            assert account.balance == 1300.00

            # Verify fact events in event store
            fact_stream = f"{ch15.Account.meta_.stream_category}-fact-{account_id}"
            fact_messages = domain.event_store.store.read(fact_stream)
            assert len(fact_messages) == 3

            last_fact = fact_messages[-1].to_domain_object()
            assert last_fact.balance == 1300.00
            assert last_fact.status == "ACTIVE"


@pytest.mark.no_test_domain
class TestESTutorialCh16(_ESTutorialBase):
    _chapter_mod = ch16

    def test_message_tracing(self):
        """Ch16: Correlation IDs and causation tree."""
        domain = ch16.domain
        with domain.domain_context():
            account_id = domain.process(
                ch16.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=5000.00,
                ),
                correlation_id="audit-trail-dep-9921",
            )
            domain.process(
                ch16.MakeDeposit(
                    account_id=account_id,
                    amount=15000.00,
                    reference="wire-transfer-001",
                ),
                correlation_id="audit-trail-dep-9921",
            )

            tree = domain.event_store.store.build_causation_tree("audit-trail-dep-9921")
            assert tree is not None

            account = domain.repository_for(ch16.Account).get(account_id)
            assert account.balance == 20000.00

    def test_correlated_deposit_and_tracing(self):
        """Ch16: a deposit joins the correlation, and trace walks up and down."""
        domain = ch16.domain
        with domain.domain_context():
            account_id = domain.process(
                ch16.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=5000.00,
                ),
                correlation_id="audit-trail-dep-9921",
            )
            ch16.make_large_deposit(account_id)

            account = domain.repository_for(ch16.Account).get(account_id)
            assert account.balance == 20000.00

            category = ch16.Account.meta_.stream_category
            deposits = [
                message
                for message in domain.event_store.store.read(f"{category}-{account_id}")
                if message.metadata.headers.type.endswith(".DepositMade.v1")
            ]
            assert len(deposits) == 1
            deposit = deposits[0]
            assert deposit.metadata.domain.correlation_id == "audit-trail-dep-9921"

            chain, effects, tree = ch16.trace(deposit.metadata.headers.id)
            command_id = chain[0].metadata.headers.id
            _, command_effects, _ = ch16.trace(command_id)

        assert [m.metadata.headers.type.rsplit(".", 2)[1] for m in chain] == [
            "MakeDeposit",
            "DepositMade",
        ]
        assert effects == []
        assert [m.metadata.headers.id for m in command_effects] == [
            deposit.metadata.headers.id
        ]
        assert tree is not None
        assert tree.message_type.endswith(".OpenAccount.v1")
        assert [child.message_type.rsplit(".", 2)[1] for child in tree.children] == [
            "AccountOpened"
        ]


@pytest.mark.no_test_domain
class TestESTutorialCh17(_ESTutorialBase):
    _chapter_mod = ch17

    def test_dead_letter_queues(self):
        """Ch17: Domain setup for DLQ workflows — process commands, verify events."""
        domain = ch17.domain
        with domain.domain_context():
            account_id = domain.process(
                ch17.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=5000.00,
                )
            )
            domain.process(
                ch17.MakeDeposit(
                    account_id=account_id,
                    amount=25000.00,
                    reference="suspicious-wire",
                )
            )

            account = domain.repository_for(ch17.Account).get(account_id)
            assert account.balance == 30000.00

            # Verify events are in the store
            stream = f"{ch17.Account.meta_.stream_category}-{account_id}"
            messages = domain.event_store.store.read(stream)
            assert len(messages) == 2


@pytest.mark.no_test_domain
class TestESTutorialCh18(_ESTutorialBase):
    _chapter_mod = ch18

    def test_monitoring_health(self):
        """Ch18: Domain with projection, process commands, verify state."""
        domain = ch18.domain
        with domain.domain_context():
            account_id = domain.process(
                ch18.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=2000.00,
                )
            )
            domain.process(
                ch18.MakeDeposit(
                    account_id=account_id, amount=500.00, reference="paycheck"
                )
            )

            account = domain.repository_for(ch18.Account).get(account_id)
            assert account.balance == 2500.00

            # Projection is maintained
            summary = domain.repository_for(ch18.AccountSummary).get(account_id)
            assert summary.balance == 2500.00
            assert summary.transaction_count == 2


@pytest.mark.no_test_domain
class TestESTutorialCh19(_ESTutorialBase):
    _chapter_mod = ch19

    def test_priority_lanes(self):
        """Ch19: BULK priority context manager routes migration events."""
        domain = ch19.domain
        with domain.domain_context():
            account_id = domain.process(
                ch19.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=5000.00,
                )
            )
            domain.process(
                ch19.MakeDeposit(
                    account_id=account_id, amount=1000.00, reference="paycheck"
                )
            )

            # Bulk migration deposits
            migration_deposits = [
                {"amount": 100.00, "reference": "migration-batch-001"},
                {"amount": 200.00, "reference": "migration-batch-002"},
                {"amount": 150.00, "reference": "migration-batch-003"},
            ]
            with ch19.processing_priority(ch19.Priority.BULK):
                for item in migration_deposits:
                    domain.process(
                        ch19.MakeDeposit(
                            account_id=account_id,
                            amount=item["amount"],
                            reference=item["reference"],
                        )
                    )

            account = domain.repository_for(ch19.Account).get(account_id)
            assert account.balance == 6450.00  # 5000 + 1000 + 100 + 200 + 150

    @staticmethod
    def _outbox_priorities(run) -> dict[object, int]:
        """Run ``run`` on a fresh copy of the chapter with the outbox on.

        Maps the account number of each ``AccountOpened`` and the amount of
        each ``DepositMade`` to the priority its outbox row carries. With
        priority lanes on, a row below the threshold of 0 goes to the
        backfill stream. A fresh copy keeps the outbox off the shared
        chapter domain.
        """
        chapter = load_example("guides/getting-started/es-tutorial/ch19.py")
        domain = chapter.domain
        domain.config["enable_outbox"] = True
        domain._initialize()
        with domain.domain_context():
            run(chapter)
            rows = domain._get_outbox_repo("default")._dao.query.all().items
        return {
            row.data.get("account_number") or row.data["amount"]: row.priority
            for row in rows
        }

    def test_migration_runs_at_bulk_priority(self, capsys):
        """Ch19: every migrated account is opened at BULK priority."""
        legacy = [
            {"number": "LEG-001", "name": "Ada Lovelace", "balance": 100.0},
            {"number": "LEG-002", "name": "Alan Turing", "balance": 250.0},
        ]

        priorities = self._outbox_priorities(
            lambda chapter: chapter.migrate_legacy_accounts(legacy)
        )

        assert priorities == {"LEG-001": -100, "LEG-002": -100}
        assert capsys.readouterr().out.splitlines() == [
            "Migrated 0 accounts...",
            "Migration complete: 2 accounts queued.",
        ]

    def test_innermost_priority_wins(self):
        """Ch19: a CRITICAL deposit inside a BULK block keeps CRITICAL."""

        def run(chapter):
            vip_id = chapter.domain.process(
                chapter.OpenAccount(
                    account_number="VIP-001",
                    holder_name="Grace Hopper",
                    opening_deposit=10.0,
                )
            )
            chapter.migrate_around_a_vip_deposit(vip_id)
            vip = chapter.domain.repository_for(chapter.Account).get(vip_id)
            assert vip.balance == 1_000_010.0

        priorities = self._outbox_priorities(run)

        assert priorities == {
            "VIP-001": 0,
            "MIGR-001": -100,
            1_000_000.0: 100,
            "MIGR-002": -100,
        }

    def test_per_command_priority(self):
        """Ch19: the priority argument applies to that one command."""

        def run(chapter):
            account_id = chapter.open_migrated_account()
            chapter.domain.process(
                chapter.MakeDeposit(account_id=account_id, amount=5.0)
            )

        priorities = self._outbox_priorities(run)

        assert priorities == {"MIGR-001": -100, 5.0: 0}


# ---------------------------------------------------------------------------
# PART V: Mastery (Ch 20-22)
# ---------------------------------------------------------------------------
@pytest.mark.no_test_domain
class TestESTutorialCh20(_ESTutorialBase):
    _chapter_mod = ch20

    def test_rebuilding_projections(self):
        """Ch20: Rebuild projection from event history."""
        domain = ch20.domain
        with domain.domain_context():
            account_id = domain.process(
                ch20.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(
                ch20.MakeDeposit(
                    account_id=account_id, amount=500.00, reference="paycheck"
                )
            )
            domain.process(
                ch20.MakeWithdrawal(
                    account_id=account_id, amount=200.00, reference="groceries"
                )
            )

            # Rebuild the projection
            result = domain.rebuild_projection(ch20.AccountSummary)
            assert result.success

            rebuilt_summary = domain.repository_for(ch20.AccountSummary).get(account_id)
            assert rebuilt_summary.balance == 1300.00
            assert rebuilt_summary.transaction_count == 3

    def test_rebuild_function_replays_every_event(self, capsys):
        """Ch20: the page's rebuild call replays all three events."""
        domain = ch20.domain
        with domain.domain_context():
            account_id = domain.process(
                ch20.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(ch20.MakeDeposit(account_id=account_id, amount=500.00))
            domain.process(ch20.MakeWithdrawal(account_id=account_id, amount=200.00))
        capsys.readouterr()

        result = ch20.rebuild_account_summaries()

        assert result.success
        assert (result.events_dispatched, result.events_skipped) == (3, 0)
        assert capsys.readouterr().out == (
            "Rebuilt 'AccountSummary': 3 events processed, 0 skipped\n"
        )
        with domain.domain_context():
            summary = domain.repository_for(ch20.AccountSummary).get(account_id)
            assert summary.balance == 1300.00


@pytest.mark.no_test_domain
class TestESTutorialCh21(_ESTutorialBase):
    _chapter_mod = ch21

    def test_event_store_database(self):
        """Ch21: Read raw events from the store, verify message structure."""
        domain = ch21.domain
        with domain.domain_context():
            account_id = domain.process(
                ch21.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=1000.00,
                )
            )
            domain.process(
                ch21.MakeDeposit(
                    account_id=account_id, amount=500.00, reference="paycheck"
                )
            )
            domain.process(
                ch21.MakeWithdrawal(
                    account_id=account_id, amount=200.00, reference="rent"
                )
            )

            # Read raw messages from the event store
            stream = f"{ch21.Account.meta_.stream_category}-{account_id}"
            messages = domain.event_store.store.read(stream)
            assert len(messages) == 3

            # Verify message metadata structure
            first_msg = messages[0]
            assert hasattr(first_msg, "metadata")
            assert first_msg.metadata.headers.type is not None

            # Reconstruct aggregate from events
            account = domain.repository_for(ch21.Account).get(account_id)
            assert account.balance == 1300.00  # 1000 + 500 - 200


@pytest.mark.no_test_domain
class TestESTutorialCh22(_ESTutorialBase):
    _chapter_mod = ch22

    def test_the_full_picture(self):
        """Ch22: Multi-aggregate domain with projections, fact events, transfer."""
        domain = ch22.domain
        with domain.domain_context():
            alice_id = domain.process(
                ch22.OpenAccount(
                    account_number="ACC-001",
                    holder_name="Alice Johnson",
                    opening_deposit=10000.00,
                )
            )
            bob_id = domain.process(
                ch22.OpenAccount(
                    account_number="ACC-002",
                    holder_name="Bob Smith",
                    opening_deposit=5000.00,
                )
            )

            domain.process(
                ch22.MakeDeposit(account_id=alice_id, amount=2000.00, reference="bonus")
            )

            # Verify aggregate state
            account_repo = domain.repository_for(ch22.Account)
            alice = account_repo.get(alice_id)
            bob = account_repo.get(bob_id)
            assert alice.balance == 12000.00
            assert bob.balance == 5000.00

            # Verify AccountSummary projection
            summary_repo = domain.repository_for(ch22.AccountSummary)
            alice_summary = summary_repo.get(alice_id)
            assert alice_summary.balance == 12000.00
            assert alice_summary.transaction_count == 2

            # Verify fact events
            fact_stream = f"{ch22.Account.meta_.stream_category}-fact-{alice_id}"
            fact_messages = domain.event_store.store.read(fact_stream)
            assert len(fact_messages) == 2
            last_fact = fact_messages[-1].to_domain_object()
            assert last_fact.balance == 12000.00

            # Initiate a transfer (stays INITIATED in sync mode)
            transfer_id = domain.process(
                ch22.InitiateTransfer(
                    source_account_id=alice_id,
                    destination_account_id=bob_id,
                    amount=3000.00,
                )
            )
            transfer = domain.repository_for(ch22.Transfer).get(transfer_id)
            assert transfer.status == "INITIATED"
