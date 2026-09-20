"""
Order aggregate with Money value object (after extraction).

Changes from extract_vo_money_before.py:
1. Extracted Money value object with add() and multiply() behavior
2. Replaced all amount+currency field pairs with ValueObject(Money)
3. Moved calculations into Money methods
4. InvoiceLine uses Money for unit_price
"""

from protean import Domain, invariant
from protean.fields import Float, HasMany, Integer, String, ValueObject

domain = Domain()


@domain.value_object
class Money:
    """Represents a monetary amount with currency."""

    amount = Float(required=True)
    currency = String(max_length=3, default="USD")

    @invariant.post
    def amount_must_be_non_negative(self):
        """Monetary amounts cannot be negative."""
        if self.amount is not None and self.amount < 0:
            from protean.exceptions import ValidationError

            raise ValidationError({"amount": ["Amount cannot be negative"]})

    def add(self, other: "Money") -> "Money":
        """Add two monetary amounts (same currency required)."""
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def multiply(self, factor: int | float) -> "Money":
        """Multiply amount by a factor."""
        return Money(amount=round(self.amount * factor, 2), currency=self.currency)


@domain.entity(part_of="Invoice")
class InvoiceLine:
    description = String(required=True, max_length=200)
    quantity = Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def line_total(self) -> Money:
        return self.unit_price.multiply(self.quantity)


@domain.aggregate
class Invoice:
    customer_id = String(required=True)
    lines = HasMany(InvoiceLine)
    subtotal = ValueObject(Money)
    tax = ValueObject(Money)
    status = String(default="DRAFT")

    def add_line(self, description: str, quantity: int, unit_price: Money) -> None:
        """Add a line item and recalculate subtotal."""
        line = InvoiceLine(
            description=description,
            quantity=quantity,
            unit_price=unit_price,
        )
        self.add_lines(line)

        line_total = unit_price.multiply(quantity)
        if self.subtotal:
            self.subtotal = self.subtotal.add(line_total)
        else:
            self.subtotal = line_total

    def apply_tax(self, rate: float) -> None:
        """Apply tax rate to subtotal."""
        if self.subtotal:
            self.tax = self.subtotal.multiply(rate)

    @property
    def total(self) -> Money | None:
        """Calculate total including tax."""
        if self.subtotal and self.tax:
            return self.subtotal.add(self.tax)
        return self.subtotal


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        invoice = Invoice(customer_id="CUST-001")
        invoice.add_line("Widget", 3, Money(amount=25.0))
        invoice.add_line("Gadget", 1, Money(amount=99.99))
        invoice.apply_tax(0.08)
        print(f"Subtotal: {invoice.subtotal.amount} {invoice.subtotal.currency}")
        print(f"Tax: {invoice.tax.amount} {invoice.tax.currency}")
        print(f"Total: {invoice.total.amount}")
