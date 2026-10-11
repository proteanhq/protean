from protean import Domain, use_case
from protean.fields import String

domain = Domain(name="Ordering")


# --8<-- [start:elements]
@domain.aggregate
class Order:
    customer = String()


class FakeGateway:
    def __init__(self):
        self.charged = []

    def charge(self, order_id):
        self.charged.append(order_id)


# --8<-- [end:elements]


# --8<-- [start:service]
@domain.application_service(part_of=Order)
class PlaceOrder:
    def __init__(self, gateway):
        self.gateway = gateway

    @use_case
    def run(self, order_id):
        self.gateway.charge(order_id)


# in a unit test
service = PlaceOrder(gateway=FakeGateway())
# --8<-- [end:service]
