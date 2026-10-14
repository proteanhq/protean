# --8<-- [start:domain]
from protean import Domain, handle
from protean.fields import HasMany, Identifier, Integer, String
from protean.utils.globals import current_domain

domain = Domain(name="Warehouse")


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    product_id: String(required=True)
    quantity: Integer(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    order_id: Identifier(required=True)


@domain.entity(part_of="Order")
class OrderItem:
    product_id: String(max_length=50, required=True)
    quantity: Integer(min_value=1, required=True)


@domain.aggregate
class Order:
    customer_id: String(max_length=50)
    status: String(max_length=20, default="placed")
    items = HasMany(OrderItem)

    @classmethod
    def create(cls, customer_id, items, **kwargs):
        order = cls(customer_id=customer_id, items=items, **kwargs)
        for item in items:
            order.raise_(
                OrderPlaced(
                    order_id=order.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                )
            )
        return order


@domain.event(part_of="Reservation")
class InventoryReserved:
    order_id: Identifier(required=True)


@domain.aggregate
class Reservation:
    order_id: Identifier(identifier=True)
    product_id: String(max_length=50, required=True)
    quantity: Integer(required=True)

    @classmethod
    def reserve(cls, order_id, product_id, quantity):
        reservation = cls(order_id=order_id, product_id=product_id, quantity=quantity)
        reservation.raise_(InventoryReserved(order_id=order_id))
        return reservation


@domain.repository(part_of=Reservation)
class ReservationRepository:
    def get_by_order(self, order_id):
        return self._dao.query.filter(order_id=order_id).all().first


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    product_id: String(required=True)
    qty: Integer(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order.create(
            customer_id="anonymous",
            items=[OrderItem(product_id=command.product_id, quantity=command.qty)],
            id=command.order_id,
        )
        current_domain.repository_for(Order).add(order)


@domain.event_handler(part_of=Order)
class InventoryHandler:
    """Reserves stock for every order placed."""

    @handle(OrderPlaced)
    def reserve(self, event: OrderPlaced):
        reservation = Reservation.reserve(
            event.order_id, event.product_id, event.quantity
        )
        current_domain.repository_for(Reservation).add(reservation)


@domain.event_handler(part_of=Reservation)
class ShippingHandler:
    """Ships an order once its stock is reserved."""

    @handle(InventoryReserved)
    def ship(self, event: InventoryReserved):
        repo = current_domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.status = "shipped"
        repo.add(order)


# --8<-- [end:domain]
