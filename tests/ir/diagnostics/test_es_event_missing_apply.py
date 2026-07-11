"""Diagnostics: TestEsEventMissingApply."""

from protean import Domain
from protean.core.aggregate import apply
from protean.fields import Identifier
from protean.fields.simple import Float, String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    build_diagnostics_test_domain,
)


class TestEsEventMissingApply:
    """Verify ES_EVENT_MISSING_APPLY diagnostics."""

    def test_missing_apply_detected(self):
        """ES aggregate with events but no @apply handler for one."""
        domain = Domain(name="EsMissing", root_path=".")

        @domain.event(part_of="Wallet")
        class WalletCreated:
            wallet_id = Identifier(identifier=True)

        @domain.event(part_of="Wallet")
        class FundsAdded:
            amount = Float(required=True)

        @domain.aggregate(is_event_sourced=True)
        class Wallet:
            balance = Float(default=0.0)

            @apply
            def created(self, event: WalletCreated) -> None:
                pass

            # No @apply for FundsAdded

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        assert len(missing) == 1
        assert "FundsAdded" in missing[0]["element"]
        assert "Wallet" in missing[0]["message"]

    def test_no_missing_apply_when_all_covered(self):
        from tests.ir.elements import build_es_aggregate_domain

        domain = build_es_aggregate_domain()
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        assert len(missing) == 0

    def test_non_es_aggregate_not_checked(self):
        """Non-ES aggregates should not trigger ES_EVENT_MISSING_APPLY."""
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        assert len(missing) == 0

    def test_fact_events_excluded_from_apply_check(self):
        """Fact events should not require @apply handlers."""
        domain = Domain(name="EsFact", root_path=".")

        @domain.event(part_of="Account")
        class AccountOpened:
            holder = String(required=True)

        @domain.aggregate(is_event_sourced=True, fact_events=True)
        class Account:
            holder = String(max_length=100, required=True)

            @apply
            def opened(self, event: AccountOpened) -> None:
                self.holder = event.holder

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        # Fact event should not be flagged
        assert len(missing) == 0

    def test_missing_apply_format(self):
        domain = Domain(name="EsFmt", root_path=".")

        @domain.event(part_of="Ledger")
        class EntryAdded:
            amount = Float(required=True)

        @domain.aggregate(is_event_sourced=True)
        class Ledger:
            total = Float(default=0.0)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        assert len(missing) == 1
        assert missing[0]["level"] == "warning"
        assert "@apply handler" in missing[0]["message"]
