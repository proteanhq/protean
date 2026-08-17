"""Diagnostics: UNRAISED_EVENT.

The producer-side mirror of UNHANDLED_EVENT: it flags a cluster event that no
aggregate or entity method raises. The rule keys on the ``raise_`` method name
plus the constructed event, never on the receiver role, so the factory idiom is
recognized. It stays in scope for published events and fails open on a class the
index cannot reach. These are the cases that keep an advisory from firing on
correct code, so the negatives carry more weight than the single positive.
"""

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.fields import String
from protean.ir.builder import IRBuilder
from protean.ir.diagnostics import REGISTRY, DiagnosticCode
from protean.utils import fqn
from tests.ir.diagnostics._helpers import _findings
from tests.ir.support import unraised_event_domain as m

CODE = DiagnosticCode.UNRAISED_EVENT.value


def _domain(name: str) -> Domain:
    return Domain(name=name, root_path=".")


class TestUnraisedEventIsFlagged:
    def test_an_event_no_method_raises_is_flagged(self):
        domain = _domain("UnraisedPositive")
        domain.register(m.Account)
        domain.register(m.Opened, part_of=m.Account)
        domain.register(m.Closed, part_of=m.Account)
        domain.init(traverse=False)

        findings = _findings(IRBuilder(domain).build(), CODE)

        assert len(findings) == 1
        d = findings[0]
        assert d["element"] == fqn(m.Closed)
        assert d["level"] == "info"
        assert d["category"] == "handler_completeness"
        assert d["message"] == "Event Closed is raised by no aggregate or entity method"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]

    def test_an_analyzed_aggregate_with_no_methods_is_flagged(self):
        """The contrast for the fail-open case below: ``Note`` has no methods but
        the index reaches its source, so it is analyzed and its unraised event is
        flagged. Fail-open gates on the class entry, not on empty methods."""
        domain = _domain("UnraisedNoMethods")
        domain.register(m.Note)
        domain.register(m.Noted, part_of=m.Note)
        domain.init(traverse=False)

        findings = _findings(IRBuilder(domain).build(), CODE)

        assert [d["element"] for d in findings] == [fqn(m.Noted)]

    def test_a_published_unraised_event_stays_in_scope(self):
        """UNHANDLED_EVENT skips published events as intentionally external; this
        rule keeps them, because a published event is still produced in the
        domain and should be raised by some method."""
        domain = _domain("UnraisedPublished")
        domain.register(m.Order)
        domain.register(m.Dispatched, part_of=m.Order)
        domain.register(m.Shipped, part_of=m.Order, published=True)
        domain.init(traverse=False)

        findings = _findings(IRBuilder(domain).build(), CODE)

        assert [d["element"] for d in findings] == [fqn(m.Shipped)]

    def test_it_is_advisory_rather_than_a_warning(self):
        assert REGISTRY[DiagnosticCode.UNRAISED_EVENT].level == "info"


class TestTheRuleStaysSilent:
    def test_a_self_raised_event_is_not_flagged(self):
        domain = _domain("UnraisedSelf")
        domain.register(m.Account)
        domain.register(m.Opened, part_of=m.Account)
        domain.init(traverse=False)

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_the_factory_idiom_raise_is_recognized(self):
        """``user.raise_(Registered(...))`` inside a classmethod leaves the
        receiver role ``UNKNOWN``. The rule keys on the ``raise_`` name and the
        constructed event, so it does not flag ``Registered``. Keying on the role
        would break this case."""
        domain = _domain("UnraisedFactory")
        domain.register(m.User)
        domain.register(m.Registered, part_of=m.User)
        domain.init(traverse=False)

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_a_published_raised_event_is_not_flagged(self):
        domain = _domain("UnraisedPublishedRaised")
        domain.register(m.Order)
        domain.register(m.Dispatched, part_of=m.Order)
        domain.init(traverse=False)

        findings = _findings(IRBuilder(domain).build(), CODE)

        assert fqn(m.Dispatched) not in [d["element"] for d in findings]
        assert findings == []

    def test_an_entity_method_raise_is_recognized(self):
        """The rule scans entity methods too: ``BasketLine.add`` raises
        ``LineAdded``, so it is not flagged even though the aggregate root raises
        nothing."""
        domain = _domain("UnraisedEntity")
        domain.register(m.Basket)
        domain.register(m.BasketLine, part_of=m.Basket)
        domain.register(m.LineAdded, part_of=m.Basket)
        domain.init(traverse=False)

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_a_fact_event_is_not_flagged(self):
        domain = _domain("UnraisedFact")
        domain.register(m.Ledger, fact_events=True)
        domain.init(traverse=False)

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_an_event_on_an_abstract_aggregate_is_not_flagged(self):
        domain = _domain("UnraisedAbstract")
        domain.register(m.AbstractBase, abstract=True)
        domain.register(m.BaseCreated, part_of=m.AbstractBase)
        domain.init(traverse=False)

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_it_fails_open_when_the_cluster_classes_are_unreachable(self):
        """A cluster whose aggregate resolves to no indexed source (here a
        dynamically-created class the index cannot reach) is skipped, so its
        unraised event is not flagged and the build still succeeds."""
        domain = _domain("UnraisedFailOpen")
        ghost = type(
            "GhostAggregate", (BaseAggregate,), {"name": String(max_length=50)}
        )
        domain.register(ghost)
        domain.register(m.Vanished, part_of=ghost)
        domain.init(traverse=False)

        assert _findings(IRBuilder(domain).build(), CODE) == []
