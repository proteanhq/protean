"""Diagnostics: TestAggregateNotNoun."""

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _assert_naming_diagnostic_shape,
)


class TestAggregateNotNoun:
    """Verify AGGREGATE_NOT_NOUN naming diagnostics."""

    def test_verb_gerund_and_adjective_aggregates_flagged(self):
        """Gerund (`OrderProcessing`), verb (`Notify`), and adjective
        (`Recursive` via `-ive`, `Cancelable` via `-able`) names are all
        flagged — the adjective suffixes are the issue's required examples."""
        domain = Domain(name="AggNaming", root_path=".")

        @domain.aggregate
        class OrderProcessing:
            reference = String(max_length=50)

        @domain.aggregate
        class Notify:
            reference = String(max_length=50)

        @domain.aggregate
        class Recursive:
            reference = String(max_length=50)

        @domain.aggregate
        class Cancelable:
            reference = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_NOT_NOUN"]
        assert len(findings) == 4
        flagged = {d["element"] for d in findings}
        assert any("OrderProcessing" in f for f in flagged)
        assert any("Notify" in f for f in flagged)
        assert any("Recursive" in f for f in flagged)
        assert any("Cancelable" in f for f in flagged)
        for diag in findings:
            _assert_naming_diagnostic_shape(diag)

    def test_agent_nouns_not_flagged(self):
        """`-er`/`-or` agent nouns must pass — they are absent from the pinned
        suffix set, not guarded by an allow-list. Regression net: trips only if
        someone *adds* an agent-noun suffix to ``NON_NOUN_AGGREGATE_SUFFIXES``."""
        domain = Domain(name="AggNamingAgents", root_path=".")

        @domain.aggregate
        class Customer:
            name = String(max_length=50)

        @domain.aggregate
        class User:
            name = String(max_length=50)

        @domain.aggregate
        class Supplier:
            name = String(max_length=50)

        @domain.aggregate
        class Auditor:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_NOT_NOUN"]
        flagged = {d["element"] for d in findings}
        assert not any("Customer" in f for f in flagged)
        assert not any("User" in f for f in flagged)
        assert not any("Supplier" in f for f in flagged)
        assert not any("Auditor" in f for f in flagged)
        assert findings == []

    def test_plain_noun_aggregates_not_flagged(self):
        domain = Domain(name="AggNamingNouns", root_path=".")

        @domain.aggregate
        class Order:
            reference = String(max_length=50)

        @domain.aggregate
        class Invoice:
            reference = String(max_length=50)

        @domain.aggregate
        class Vendor:
            reference = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_NOT_NOUN"]
        assert findings == []

    def test_ate_nouns_not_flagged(self):
        """Regression guard for the pinned set: `-ate` is deliberately NOT a
        flagged suffix, so common domain nouns ending in `-ate` (`State`,
        `Certificate`, `Template`, `Estimate`) must pass. Adding `-ate` back
        would reintroduce false positives on these legitimate nouns."""
        domain = Domain(name="AggNamingAte", root_path=".")

        @domain.aggregate
        class State:
            reference = String(max_length=50)

        @domain.aggregate
        class Certificate:
            reference = String(max_length=50)

        @domain.aggregate
        class Template:
            reference = String(max_length=50)

        @domain.aggregate
        class Estimate:
            reference = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_NOT_NOUN"]
        assert findings == []

    def test_infrastructure_aggregate_skipped(self):
        """An aggregate whose FQN is under ``protean.adapters.`` is skipped even
        when its name (`Shipping`) ends in a flagged suffix."""

        domain = Domain(name="AggNamingInfra", root_path=".")

        class Shipping(BaseAggregate):
            reference = String(max_length=50)

        Shipping.__module__ = "protean.adapters.fake"
        domain.register(Shipping)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_NOT_NOUN"]
        assert not any("Shipping" in d["element"] for d in findings)
        assert findings == []

    def test_name_equal_to_suffix_not_flagged(self):
        """Length guard: a name exactly equal to a suffix (`Able`) must not
        self-match (name length must strictly exceed the suffix length)."""
        domain = Domain(name="AggNamingGuard", root_path=".")

        @domain.aggregate
        class Able:
            reference = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_NOT_NOUN"]
        assert findings == []
