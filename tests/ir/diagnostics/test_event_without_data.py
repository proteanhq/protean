"""Diagnostics: TestEventWithoutData."""

from protean import Domain
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder


class TestEventWithoutData:
    """Detect events with zero user-defined fields."""

    def test_empty_event_detected(self):
        domain = Domain(name="EmptyEventTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order)
        class OrderNudged:
            pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "EVENT_WITHOUT_DATA"]
        assert len(diags) == 1
        assert diags[0]["level"] == "info"
        assert "OrderNudged" in diags[0]["message"]

    def test_no_warning_when_event_has_fields(self):
        domain = Domain(name="FieldEventTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "EVENT_WITHOUT_DATA" not in codes

    def test_fact_events_excluded(self):
        """Fact events are auto-generated and should not be flagged."""
        domain = Domain(name="FactEventTest", root_path=".")

        @domain.aggregate(fact_events=True)
        class Order:
            name = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Find the Order cluster (not MemoryMessage)
        order_cluster = next(
            c for c in ir["clusters"].values() if c["aggregate"]["name"] == "Order"
        )
        fact_events = [
            e for e in order_cluster["events"].values() if e.get("is_fact_event", False)
        ]
        assert len(fact_events) > 0, "Expected at least one fact event"

        # The fact event should NOT trigger EVENT_WITHOUT_DATA
        diags = [d for d in ir["diagnostics"] if d["code"] == "EVENT_WITHOUT_DATA"]
        assert len(diags) == 0
