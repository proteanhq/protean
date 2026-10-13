from protean import Domain, handle
from protean.fields import Boolean, Float, Identifier

domain = Domain(name="Shop")


# --8<-- [start:order_model]
@domain.aggregate
class Order:
    client_id: Identifier(required=True)
    total: Float(required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    client_id: Identifier(required=True)
    total: Float(required=True)


# --8<-- [end:order_model]


# --8<-- [start:event_handler]
@domain.event_handler(part_of=Order, sequential_by="client_id")
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None: ...


# --8<-- [end:event_handler]


# --8<-- [start:product_model]
from protean.core.projector import on
from protean.fields import String


@domain.aggregate
class Product:
    name: String(required=True)


@domain.event(part_of=Product)
class ProductCreated:
    product_id: Identifier(required=True)
    name: String(required=True)


@domain.event(part_of=Product)
class ProductActivated:
    product_id: Identifier(required=True)


@domain.projection
class ProductSummary:
    product_id: Identifier(identifier=True)
    name: String()
    active: Boolean(default=False)


# --8<-- [end:product_model]


# --8<-- [start:projector]
@domain.projector(
    projector_for=ProductSummary, aggregates=[Product], sequential_by="product_id"
)
class ProductSummaryProjector:
    @on(ProductCreated)
    def on_created(self, event: ProductCreated) -> None: ...

    @on(ProductActivated)
    def on_activated(self, event: ProductActivated) -> None: ...


# --8<-- [end:projector]


# --8<-- [start:payment_model]
@domain.aggregate
class Payment:
    order_id: Identifier(required=True)


@domain.event(part_of=Payment)
class PaymentConfirmed:
    order_id: Identifier(required=True)


# --8<-- [end:payment_model]


# --8<-- [start:process_manager]
@domain.process_manager(sequential_by=True)
class OrderFulfillment:
    order_id = Identifier(identifier=True)

    @handle(PaymentConfirmed, start=True, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None: ...


# --8<-- [end:process_manager]
