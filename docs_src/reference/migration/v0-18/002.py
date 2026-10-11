from protean import Domain
from protean.fields import Identifier, String

domain = Domain(name="Ordering")


@domain.event(part_of="Order")
class OrderShipped:
    order_id: Identifier(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    order_id: Identifier(required=True)


@domain.aggregate
class Order:
    status: String(max_length=20, default="pending")

    def ship(self):
        self.status = "shipped"
        self.raise_(OrderShipped(order_id=self.id))

    def cancel(self):
        self.status = "cancelled"
        self.raise_(OrderCancelled(order_id=self.id))


# --8<-- [start:single]
def ship_order(order_id):
    # Load, invoke a behaviour method, add
    repo = domain.repository_for(Order)
    order = repo.get(order_id)
    order.ship()  # the aggregate applies the change and raises OrderShipped
    repo.add(order)


# --8<-- [end:single]


# --8<-- [start:many]
def cancel_pending_orders():
    # Load each match and invoke the behaviour method on it
    repo = domain.repository_for(Order)
    for order in repo.query.filter(status="pending").all():
        order.cancel()
        repo.add(order)


# --8<-- [end:many]
