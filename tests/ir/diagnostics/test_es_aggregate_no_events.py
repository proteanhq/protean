"""Diagnostics: TestESAggregateNoEvents."""

from protean import Domain
from protean.fields.simple import Float
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.diagnostics._helpers import (
    _codes_for,
)


class TestESAggregateNoEvents:
    """ES_AGGREGATE_NO_EVENTS flags an ``event_sourced=True`` aggregate with no
    events (it cannot reconstitute state)."""

    def test_es_aggregate_without_events_flagged(self):
        domain = Domain(name="ESNoEvents", root_path=".")

        @domain.aggregate(event_sourced=True)
        class Account:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "ES_AGGREGATE_NO_EVENTS"]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(Account)
        assert d["level"] == "warning"
        assert d["category"] == "aggregate_design"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_es_aggregate_with_event_not_flagged(self):
        domain = Domain(name="ESWithEvent", root_path=".")

        @domain.aggregate(event_sourced=True)
        class Account:
            balance = Float()

        @domain.event(part_of=Account)
        class Deposited:
            amount = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "ES_AGGREGATE_NO_EVENTS" not in codes

    def test_non_event_sourced_without_events_not_flagged(self):
        """The ``is_event_sourced`` guard fails first for a plain aggregate."""
        domain = Domain(name="NonESNoEvents", root_path=".")

        @domain.aggregate
        class Account:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "ES_AGGREGATE_NO_EVENTS" not in codes

    def test_fact_events_do_not_count_as_domain_events(self):
        """The framework-generated ``FactEvent`` (``auto_generated``) lands in
        ``cluster["events"]`` but cannot reconstitute an ES aggregate by replay,
        so an ES aggregate with only fact events is still flagged."""
        domain = Domain(name="ESFactOnly", root_path=".")

        @domain.aggregate(event_sourced=True, fact_events=True)
        class Account:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "ES_AGGREGATE_NO_EVENTS"]
        assert len(diags) == 1
        assert diags[0]["element"] == fqn(Account)

    def test_abstract_es_aggregate_not_flagged(self):
        """An abstract ``event_sourced=True`` aggregate with no events is skipped
        — the missing-events shape only exists on a non-instantiable base."""
        domain = Domain(name="ESAbstract", root_path=".")

        @domain.aggregate(event_sourced=True, abstract=True)
        class BaseAccount:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "ES_AGGREGATE_NO_EVENTS" not in codes

    def test_infrastructure_aggregate_not_flagged(self):
        """A framework/infrastructure ES aggregate (FQN under
        ``protean.adapters.``) with no events is skipped. Deleting the
        ``protean.adapters.`` guard must fail this test."""
        domain = Domain(name="ESInfra", root_path=".")

        @domain.aggregate(event_sourced=True)
        class Account:
            balance = Float()

        # Masquerade as an infrastructure aggregate so its cluster FQN sits under
        # ``protean.adapters.`` (real adapter aggregates are internal and never
        # clustered, so this override is how the guard is reached).
        Account.__module__ = "protean.adapters.fake"

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "ES_AGGREGATE_NO_EVENTS" not in codes

    def test_suppress_checks_drops_code(self):
        domain = Domain(name="ESSuppress", root_path=".")

        @domain.aggregate(
            event_sourced=True, suppress_checks=["ES_AGGREGATE_NO_EVENTS"]
        )
        class Account:
            balance = Float()

        @domain.aggregate(event_sourced=True)
        class Ledger:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed on Account, yet the identical shape on Ledger still fires.
        assert "ES_AGGREGATE_NO_EVENTS" not in _codes_for(ir, "Account")
        assert "ES_AGGREGATE_NO_EVENTS" in _codes_for(ir, "Ledger")
