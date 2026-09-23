"""
Cross-aggregate read model: Projection combining data from multiple aggregates.

This example demonstrates:
- A projection that combines data from Customer and Order aggregates
- A projector listening to events from two different aggregates
- Handling initialization events (customer registered) and update events (order placed)
- Building a denormalized summary view spanning aggregate boundaries
- Graceful handling of incremental updates

Domain: A customer order summary that shows each customer's name,
total number of orders, and total amount spent - data that spans
the Customer and Order aggregates.
"""

from protean import Domain
from protean.core.projector import on
from protean.fields import Float, Identifier, Integer, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Customer")
class CustomerRegistered:
    """Raised when a new customer registers."""

    customer_id: Identifier(required=True)
    name: String(required=True)
    email: String(required=True)


@domain.event(part_of="Order")
class OrderPlaced:
    """Raised when a customer places an order."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total_amount: Float(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    """Raised when an order is cancelled."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    refund_amount: Float(required=True)


# --- Aggregates (write models) ---


@domain.aggregate
class Customer:
    """Customer aggregate."""

    name: String(required=True, max_length=100)
    email: String(required=True, max_length=200)

    @classmethod
    def register(cls, name, email):
        """Register a new customer."""
        customer = cls(name=name, email=email)
        customer.raise_(
            CustomerRegistered(
                customer_id=customer.id,
                name=customer.name,
                email=customer.email,
            )
        )
        return customer


@domain.aggregate
class Order:
    """Order aggregate."""

    customer_id: Identifier(required=True)
    total_amount: Float(required=True)
    status: String(default="placed")

    @classmethod
    def place(cls, customer_id, total_amount):
        """Place a new order."""
        order = cls(customer_id=customer_id, total_amount=total_amount)
        order.raise_(
            OrderPlaced(
                order_id=order.id,
                customer_id=customer_id,
                total_amount=total_amount,
            )
        )
        return order

    def cancel(self):
        """Cancel this order."""
        self.status = "cancelled"
        self.raise_(
            OrderCancelled(
                order_id=self.id,
                customer_id=self.customer_id,
                refund_amount=self.total_amount,
            )
        )


# --- Projection (read model) ---


@domain.projection
class CustomerOrderSummary:
    """Cross-aggregate projection combining Customer and Order data.

    Tracks each customer's order count and total spending.
    Populated by events from both Customer and Order aggregates.
    """

    customer_id: Identifier(identifier=True, required=True)
    customer_name: String(max_length=100, required=True)
    email: String(max_length=200)
    order_count: Integer(default=0)
    total_spent: Float(default=0.0)


# --- Projector ---


@domain.projector(
    projector_for=CustomerOrderSummary,
    aggregates=[Customer, Order],
)
class CustomerOrderSummaryProjector:
    """Maintains the CustomerOrderSummary from Customer and Order events.

    Listens to:
    - CustomerRegistered: Initialize the summary record
    - OrderPlaced: Increment order count and total spent
    - OrderCancelled: Decrement order count and reduce total spent
    """

    @on(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        """Initialize a summary record when a customer registers."""
        repo = domain.repository_for(CustomerOrderSummary)
        summary = CustomerOrderSummary(
            customer_id=event.customer_id,
            customer_name=event.name,
            email=event.email,
            order_count=0,
            total_spent=0.0,
        )
        repo.add(summary)

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        """Update summary when an order is placed."""
        repo = domain.repository_for(CustomerOrderSummary)
        summary = repo.get(event.customer_id)
        summary.order_count += 1
        summary.total_spent += event.total_amount
        repo.add(summary)

    @on(OrderCancelled)
    def on_order_cancelled(self, event: OrderCancelled):
        """Update summary when an order is cancelled."""
        repo = domain.repository_for(CustomerOrderSummary)
        summary = repo.get(event.customer_id)
        summary.order_count -= 1
        summary.total_spent -= event.refund_amount
        repo.add(summary)
