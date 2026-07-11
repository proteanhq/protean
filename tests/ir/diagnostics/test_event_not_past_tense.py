"""Diagnostics: TestEventNotPastTense."""

from protean import Domain
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _assert_naming_diagnostic_shape,
)


class TestEventNotPastTense:
    """Verify EVENT_NOT_PAST_TENSE naming diagnostics."""

    def test_gerund_events_flagged(self):
        domain = Domain(name="EventNaming", root_path=".")

        @domain.event(part_of="Order")
        class OrderCreating:
            order_id = Identifier(identifier=True)

        @domain.event(part_of="Order")
        class OrderProcessing:
            order_id = Identifier(identifier=True)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "EVENT_NOT_PAST_TENSE"]
        assert len(findings) == 2
        flagged = {d["element"] for d in findings}
        assert any("OrderCreating" in f for f in flagged)
        assert any("OrderProcessing" in f for f in flagged)
        for diag in findings:
            _assert_naming_diagnostic_shape(diag)

    def test_past_tense_events_not_flagged(self):
        domain = Domain(name="EventNamingClean", root_path=".")

        @domain.event(part_of="Order")
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.event(part_of="Order")
        class OrderCreated:
            order_id = Identifier(identifier=True)

        @domain.event(part_of="Order")
        class OrderCancelled:
            order_id = Identifier(identifier=True)

        @domain.event(part_of="Order")
        class OrderStatus:
            order_id = Identifier(identifier=True)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "EVENT_NOT_PAST_TENSE"]
        assert findings == []

    def test_framework_events_skipped(self):
        """The ``auto_generated``/``is_fact_event`` guard is load-bearing.

        An auto-generated event ending in ``-ing`` is framework-synthesized,
        not user-named, so it is skipped; the user-defined gerund event
        alongside it is flagged. This is the only branch of the guard that can
        be exercised behaviourally — fact events are always named
        ``<Aggregate>FactEvent`` and never end in ``-ing``, so the
        ``is_fact_event`` half is untestable defensive code. Reverting the
        guard turns the ``OrderSyncing`` assertion red.
        """
        from protean.core.event import BaseEvent

        domain = Domain(name="EventNamingFramework", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of="Order")
        class OrderShipping:
            order_id = Identifier(identifier=True)

        class OrderSyncing(BaseEvent):
            order_id = Identifier(identifier=True)

        domain.register(OrderSyncing, part_of="Order", auto_generated=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        findings = [d for d in ir["diagnostics"] if d["code"] == "EVENT_NOT_PAST_TENSE"]
        flagged = {d["element"] for d in findings}
        # User-named gerund event IS flagged.
        assert any("OrderShipping" in f for f in flagged)
        # Auto-generated (framework) gerund event is skipped by the guard.
        assert not any("OrderSyncing" in f for f in flagged)
