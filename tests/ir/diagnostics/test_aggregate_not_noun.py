"""Diagnostics: TestAggregateNotNoun."""

import pytest

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
        flagged. The adjective suffixes are the issue's required examples."""
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

    @pytest.mark.parametrize(
        "names",
        [
            ["Customer", "User", "Supplier", "Auditor"],
            ["Order", "Invoice", "Vendor"],
            ["State", "Certificate", "Template", "Estimate"],
            ["Able"],
        ],
        ids=[
            "agent-nouns-ending-in-er-or-or",
            "plain-nouns",
            "nouns-ending-in-ate",
            "name-equal-to-a-suffix",
        ],
    )
    def test_noun_aggregates_are_not_flagged(self, names):
        """Noun names pass. Agent nouns (`-er`, `-or`) and nouns ending in
        `-ate` pass because those endings are absent from the pinned suffix
        set; the test fails if someone adds one of them to
        ``NON_NOUN_AGGREGATE_SUFFIXES``. A name exactly equal to a suffix
        (`Able`) does not match itself, because the name must be longer than
        the suffix."""
        domain = Domain(name="AggNamingNouns", root_path=".")
        for name in names:
            domain.aggregate(type(name, (), {"reference": String(max_length=50)}))

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
