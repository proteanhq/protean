# --8<-- [start:domain]
from protean import Domain
from protean.fields import Float, HasMany, Integer, String

domain = Domain(name="Shop")


@domain.entity(part_of="Order")
class OrderItem:
    product_id: String(max_length=50, required=True)
    quantity: Integer(min_value=1, required=True)


@domain.aggregate
class Ticket:
    title: String(max_length=100, required=True)
    status: String(max_length=20, default="PENDING")


@domain.repository(part_of=Ticket)
class TicketRepository:
    def find_pending(self, limit):
        query = self._dao.query.filter(status="PENDING").limit(limit)
        return query.all(with_total=False).items

    def count_pending(self):
        return self._dao.query.filter(status="PENDING").count()


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    status: String(max_length=20, default="PENDING")
    total_amount: Float(default=0.0)
    items = HasMany(OrderItem)


# --8<-- [end:domain]
