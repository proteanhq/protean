"""Diagnostics: TestPublishedNoExternalBroker."""

from protean import Domain
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder


class TestPublishedNoExternalBroker:
    """Detect published events with no external brokers configured."""

    def test_published_event_without_broker_flagged(self):
        domain = Domain(name="PubNoBrokerTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order, published=True)
        class OrderShipped:
            order_id = Identifier(required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "PUBLISHED_NO_EXTERNAL_BROKER"
        ]
        assert len(diags) == 1
        assert diags[0]["level"] == "warning"

    def test_no_warning_when_external_broker_configured(self):
        domain = Domain(name="PubWithBrokerTest", root_path=".")
        domain.config["outbox"] = {"external_brokers": ["redis"]}

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order, published=True)
        class OrderShipped:
            order_id = Identifier(required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "PUBLISHED_NO_EXTERNAL_BROKER" not in codes
