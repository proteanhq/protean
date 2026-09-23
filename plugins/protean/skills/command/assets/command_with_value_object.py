"""
Command with value objects for complex immutable data.

This example demonstrates:
- Commands containing value objects (Money, Address)
- Using ValueObject() field to reference value objects
- Type safety and validation through value objects
- Multiple value objects in a single command
- Value object reusability across commands

Usage:
    from protean import Domain
    domain = Domain()

    command = UpdateCustomerAddress(
        customer_id="CUST-001",
        new_address=Address(street="123 Main St", city="SF", ...),
    )
"""

from protean import Domain
from protean.fields import Float, Identifier, String, ValueObject

# Domain setup
domain = Domain()


@domain.value_object
class Money:
    """Value object representing monetary amounts with currency."""

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        """Add two money values (must be same currency)."""
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)


@domain.value_object
class Address:
    """Value object representing a physical address."""

    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)


# Aggregates (required for commands to reference)
@domain.aggregate
class Order:
    """Order aggregate."""

    order_id: Identifier(required=True)


@domain.aggregate
class Customer:
    """Customer aggregate."""

    customer_id: Identifier(required=True)


@domain.aggregate
class Payment:
    """Payment aggregate."""

    payment_id: Identifier(required=True)


@domain.command(part_of="Order")
class PlaceOrder:
    """Command to place an order, including value objects."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)

    # Value objects for complex data
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)


@domain.command(part_of="Customer")
class UpdateCustomerAddress:
    """Command to update a customer's address."""

    customer_id: Identifier(required=True)

    # Address value object for the new address
    new_address = ValueObject(Address, required=True)


@domain.command(part_of="Payment")
class InitiatePayment:
    """Command to initiate a payment."""

    payment_id: Identifier(required=True)
    order_id: String(required=True)

    # Money value object for payment amount
    amount = ValueObject(Money, required=True)

    payment_method: String(required=True, max_length=50)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create value objects
        total = Money(amount=149.99, currency="USD")

        shipping_addr = Address(
            street="456 Market Street",
            city="San Francisco",
            state="CA",
            postal_code="94102",
            country="USA",
        )

        billing_addr = Address(
            street="789 Mission Street",
            city="San Francisco",
            state="CA",
            postal_code="94103",
            country="USA",
        )

        # Create command with value objects
        place_order = PlaceOrder(
            order_id="ORD-98765",
            customer_id="CUST-12345",
            total=total,
            shipping_address=shipping_addr,
            billing_address=billing_addr,
        )

        print(f"Command: {place_order.__class__.__name__}")
        print(f"Order ID: {place_order.order_id}")
        print(f"Total: {place_order.total.amount} {place_order.total.currency}")
        print(
            f"Shipping: {place_order.shipping_address.street}, "
            f"{place_order.shipping_address.city}, "
            f"{place_order.shipping_address.state}"
        )

        # Update customer address command
        update_address = UpdateCustomerAddress(
            customer_id="CUST-12345",
            new_address=Address(
                street="100 New Street",
                city="Oakland",
                state="CA",
                postal_code="94601",
                country="USA",
            ),
        )

        print(f"\nCommand: {update_address.__class__.__name__}")
        print(f"New City: {update_address.new_address.city}")

        # Initiate payment command
        payment = InitiatePayment(
            payment_id="PAY-001",
            order_id="ORD-98765",
            amount=Money(amount=149.99, currency="USD"),
            payment_method="credit_card",
        )

        print(f"\nCommand: {payment.__class__.__name__}")
        print(f"Payment Amount: {payment.amount.amount} {payment.amount.currency}")
        print(f"Payment Method: {payment.payment_method}")

        # Value objects in commands are immutable
        try:
            total.amount = 999.99
        except Exception as e:
            print(f"\nValue objects are immutable: {type(e).__name__}")
