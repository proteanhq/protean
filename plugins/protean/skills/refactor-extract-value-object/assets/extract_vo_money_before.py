"""
Order aggregate with primitive money fields (before extraction).

This example demonstrates primitive obsession: amount + currency fields
appear as separate primitives on both the aggregate and its entity,
with calculations scattered in methods.

The refactored version is in extract_vo_money_after.py.
"""

from protean import Domain
from protean.fields import Float, HasMany, Integer, String

domain = Domain()


@domain.entity(part_of="Invoice")
class InvoiceLine:
    description = String(required=True, max_length=200)
    quantity = Integer(required=True, min_value=1)
    unit_price_amount = Float(required=True)
    unit_price_currency = String(default="USD")

    @property
    def line_total_amount(self) -> float:
        return self.unit_price_amount * self.quantity


@domain.aggregate
class Invoice:
    customer_id = String(required=True)
    lines = HasMany(InvoiceLine)
    subtotal_amount = Float(default=0.0)
    subtotal_currency = String(default="USD")
    tax_amount = Float(default=0.0)
    tax_currency = String(default="USD")
    status = String(default="DRAFT")

    def add_line(self, description: str, quantity: int, unit_price: float) -> None:
        """Add a line item and recalculate subtotal."""
        line = InvoiceLine(
            description=description,
            quantity=quantity,
            unit_price_amount=unit_price,
            unit_price_currency=self.subtotal_currency,
        )
        self.add_lines(line)
        self.subtotal_amount += unit_price * quantity

    def apply_tax(self, rate: float) -> None:
        """Apply tax rate to subtotal."""
        self.tax_amount = self.subtotal_amount * rate
        self.tax_currency = self.subtotal_currency

    @property
    def total_amount(self) -> float:
        return self.subtotal_amount + self.tax_amount


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        invoice = Invoice(customer_id="CUST-001")
        invoice.add_line("Widget", 3, 25.0)
        invoice.add_line("Gadget", 1, 99.99)
        invoice.apply_tax(0.08)
        print(f"Subtotal: {invoice.subtotal_amount} {invoice.subtotal_currency}")
        print(f"Tax: {invoice.tax_amount} {invoice.tax_currency}")
        print(f"Total: {invoice.total_amount}")
