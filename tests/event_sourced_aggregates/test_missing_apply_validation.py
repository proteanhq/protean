"""Tests for Finding #6: ES events without @apply handlers produce warnings.

Every event declared with part_of=AnEventSourcedAggregate should have a
corresponding @apply handler. Missing handlers are caught during
_validate_domain() and logged as warnings to alert developers early.
"""

import logging


from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.fields import Identifier, Integer, String


class Deposited(BaseEvent):
    account_id: Identifier()
    amount: Integer()


class Withdrawn(BaseEvent):
    account_id: Identifier()
    amount: Integer()


class Account(BaseAggregate):
    account_id: Identifier(identifier=True)
    balance: Integer(default=0)

    @apply
    def deposited(self, event: Deposited) -> None:
        self.balance += event.amount


class TestMissingApplyValidation:
    """Tests that missing @apply handlers produce warnings at domain init."""

    def test_event_without_apply_warns_at_init(self, test_domain, caplog):
        """An ES event without an @apply handler triggers a warning."""
        test_domain.register(Account, is_event_sourced=True)
        test_domain.register(Deposited, part_of=Account)
        test_domain.register(Withdrawn, part_of=Account)  # No @apply for this

        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        assert any(
            "Withdrawn" in r.message
            and "Account" in r.message
            and "@apply handler" in r.message
            for r in caplog.records
        )

    def test_all_events_with_apply_no_warning(self, test_domain, caplog):
        """When every ES event has an @apply handler, no warning is produced."""

        class FullAccount(BaseAggregate):
            account_id: Identifier(identifier=True)
            balance: Integer(default=0)

            @apply
            def deposited(self, event: Deposited) -> None:
                self.balance += event.amount

            @apply
            def withdrawn(self, event: Withdrawn) -> None:
                self.balance -= event.amount

        test_domain.register(FullAccount, is_event_sourced=True)
        test_domain.register(Deposited, part_of=FullAccount)
        test_domain.register(Withdrawn, part_of=FullAccount)

        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        assert not any("@apply handler" in r.message for r in caplog.records)

    def test_non_es_aggregate_events_not_checked(self, test_domain, caplog):
        """Events on non-event-sourced aggregates are not subject to @apply check."""

        class RegularAggregate(BaseAggregate):
            name: String()

        class SomethingHappened(BaseEvent):
            name: String()

        test_domain.register(RegularAggregate)
        test_domain.register(SomethingHappened, part_of=RegularAggregate)

        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        assert not any("@apply handler" in r.message for r in caplog.records)

    def test_event_from_different_aggregate_not_warned(self, test_domain, caplog):
        """Only events belonging to the ES aggregate trigger warnings."""

        class OtherAggregate(BaseAggregate):
            name: String()

        class OtherEvent(BaseEvent):
            name: String()

        test_domain.register(Account, is_event_sourced=True)
        test_domain.register(Deposited, part_of=Account)
        test_domain.register(OtherAggregate)
        test_domain.register(OtherEvent, part_of=OtherAggregate)

        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        # No warnings for Account (Deposited has @apply) or OtherAggregate (non-ES)
        assert not any("@apply handler" in r.message for r in caplog.records)

    def test_warning_message_names_event_and_aggregate(self, test_domain, caplog):
        """The warning message clearly identifies the offending event and aggregate."""

        class Ledger(BaseAggregate):
            ledger_id: Identifier(identifier=True)

        class EntryRecorded(BaseEvent):
            ledger_id: Identifier()

        test_domain.register(Ledger, is_event_sourced=True)
        test_domain.register(EntryRecorded, part_of=Ledger)

        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        matching = [
            r
            for r in caplog.records
            if "EntryRecorded" in r.message and "Ledger" in r.message
        ]
        assert len(matching) == 1

    def test_fact_events_excluded_from_check(self, test_domain, caplog):
        """Fact events (auto-generated) should not trigger warnings."""

        class Wallet(BaseAggregate):
            wallet_id: Identifier(identifier=True)
            balance: Integer(default=0)

        class WalletCreated(BaseEvent):
            wallet_id: Identifier()

        test_domain.register(Wallet, is_event_sourced=True, fact_events=True)
        test_domain.register(WalletCreated, part_of=Wallet)

        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        # WalletCreated lacks @apply — should warn
        assert any("WalletCreated" in r.message for r in caplog.records)
        # WalletFactEvent (auto-generated) — should NOT warn
        assert not any("FactEvent" in r.message for r in caplog.records)
