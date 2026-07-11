"""Diagnostics: TestAggregateTooLarge."""

from protean import Domain
from protean.fields.simple import Float, String
from protean.ir.builder import IRBuilder


class TestAggregateTooLarge:
    """Detect aggregate clusters with too many entities."""

    def test_large_aggregate_detected(self):
        domain = Domain(name="LargeAggTest", root_path=".")
        # Set limit low for testing
        domain.config["lint"] = {"aggregate_size_limit": 2}

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.entity(part_of=Order)
        class LineItem:
            sku = String(max_length=50)

        @domain.entity(part_of=Order)
        class Discount:
            code = String(max_length=20)

        @domain.entity(part_of=Order)
        class Payment:
            amount = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_TOO_LARGE"]
        assert len(diags) == 1
        assert diags[0]["level"] == "info"
        assert "Order" in diags[0]["message"]
        assert "3 entities" in diags[0]["message"]

    def test_no_warning_when_under_limit(self):
        domain = Domain(name="SmallAggTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.entity(part_of=Order)
        class LineItem:
            sku = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_TOO_LARGE" not in codes
