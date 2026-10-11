# --8<-- [start:elements]
from protean import Domain, current_domain
from protean.core.projector import on
from protean.fields import Float, Identifier, Integer, String

domain = Domain(name="Shop")


@domain.aggregate
class Customer:
    name: String(required=True)


@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.aggregate
class Payment:
    customer_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Inventory:
    sku: String(required=True)


@domain.event(part_of=Customer)
class CustomerRegistered:
    customer_id: Identifier(required=True)
    name: String(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.event(part_of=Payment)
class PaymentProcessed:
    payment_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    amount: Float(required=True)


@domain.projection
class CustomerOrderSummary:
    customer_id: Identifier(identifier=True)
    name: String()
    order_count: Integer(default=0)
    order_total: Float(default=0.0)
    amount_paid: Float(default=0.0)


@domain.projection
class SystemMetrics:
    name: String(identifier=True)
    customers: Integer(default=0)
    orders: Integer(default=0)


# --8<-- [end:elements]


# --8<-- [start:cross_aggregate]
@domain.projector(
    projector_for=CustomerOrderSummary, aggregates=[Customer, Order, Payment]
)
class CustomerOrderSummaryProjector:
    @on(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        # Initialize customer summary
        current_domain.repository_for(CustomerOrderSummary).add(
            CustomerOrderSummary(customer_id=event.customer_id, name=event.name)
        )

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Update order count and total
        repository = current_domain.repository_for(CustomerOrderSummary)
        summary = repository.get(event.customer_id)
        summary.order_count += 1
        summary.order_total += event.total
        repository.add(summary)

    @on(PaymentProcessed)
    def on_payment_processed(self, event: PaymentProcessed):
        # Update payment status
        repository = current_domain.repository_for(CustomerOrderSummary)
        summary = repository.get(event.customer_id)
        summary.amount_paid += event.amount
        repository.add(summary)


# --8<-- [end:cross_aggregate]


# --8<-- [start:stream_categories]
@domain.projector(
    projector_for=SystemMetrics,
    stream_categories=[
        Customer.meta_.stream_category,  # "<domain>::customer"
        Order.meta_.stream_category,  # "<domain>::order"
        Payment.meta_.stream_category,  # "<domain>::payment"
        Inventory.meta_.stream_category,  # "<domain>::inventory"
    ],
)
class SystemMetricsProjector:
    @on(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        # Update customer metrics
        metrics = self._metrics()
        metrics.customers += 1
        current_domain.repository_for(SystemMetrics).add(metrics)

    @on(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Update order metrics
        metrics = self._metrics()
        metrics.orders += 1
        current_domain.repository_for(SystemMetrics).add(metrics)

    def _metrics(self):
        repository = current_domain.repository_for(SystemMetrics)
        return repository.get_or_none("all") or SystemMetrics(name="all")


# --8<-- [end:stream_categories]
