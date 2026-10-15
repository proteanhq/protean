# --8<-- [start:model]
from protean import Domain, handle
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain(name="Ordering")


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    subtotal: Float(default=0.0)
    tax: Float(default=0.0)
    shipping: Float(default=0.0)
    status: String(max_length=20, default="draft")

    def place(self) -> None:
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_name=self.customer_name,
                subtotal=self.subtotal,
                tax=self.tax,
                shipping=self.shipping,
            )
        )

    def ship(self) -> None:
        self.status = "shipped"
        self.raise_(OrderShipped(order_id=self.id))


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_name: String(max_length=100)
    subtotal: Float()
    tax: Float()
    shipping: Float()


@domain.event(part_of=Order)
class OrderShipped:
    order_id: Identifier(required=True)


# --8<-- [end:model]


# --8<-- [start:before]
@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    customer_name: String(max_length=100)
    total: Float()
    status: String(max_length=20)


# --8<-- [end:before]


@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderSummary)
        repo.add(
            OrderSummary(
                order_id=event.order_id,
                customer_name=event.customer_name,
                total=event.subtotal + event.tax + event.shipping,
                status="placed",
            )
        )


domain.init(traverse=False)
