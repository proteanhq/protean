from protean import Domain, handle
from protean.fields import Identifier, String

domain = Domain(name="Ordering")
domain.config["event_processing"] = "sync"


class OutOfStock(Exception):
    pass


class Stock:
    """Stands in for a stock service. It fails while `available` is False."""

    def __init__(self):
        self.available = True
        self.reserved = []

    def reserve(self, order_id):
        if not self.available:
            raise OutOfStock(order_id)
        self.reserved.append(order_id)


class PartnerDown(Exception):
    pass


class Partner:
    """Stands in for a partner system. It fails while `available` is False."""

    def __init__(self):
        self.available = True
        self.notified = []

    def notify(self, order_id):
        if not self.available:
            raise PartnerDown(order_id)
        self.notified.append(order_id)


stock = Stock()
partner = Partner()


@domain.aggregate
class Order:
    customer = String()

    @classmethod
    def place(cls, customer):
        order = cls(customer=customer)
        order.raise_(OrderPlaced(order_id=order.id))
        return order


@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)


# --8<-- [start:handlers]
@domain.event_handler(part_of=Order)
class ReserveStock:
    @handle(OrderPlaced)
    def reserve(self, event):
        stock.reserve(event.order_id)  # may raise


@domain.event_handler(part_of=Order)
class NotifyPartner:
    @handle(OrderPlaced)
    def notify(self, event):
        partner.notify(event.order_id)  # before: might never run under sync
        # after: no longer skipped


# --8<-- [end:handlers]
