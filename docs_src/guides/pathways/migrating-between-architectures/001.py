# --8<-- [start:model]
from fastapi import FastAPI

from protean import Domain, current_domain, use_case
from protean.fields import Float, HasMany, Identifier, Integer, String
from protean.integrations.fastapi import DomainContextMiddleware

domain = Domain(name="Shop")


@domain.entity(part_of="Order")
class OrderItem:
    product_id = Identifier(required=True)
    quantity = Integer(min_value=1, default=1)


@domain.aggregate
class Order:
    customer_id = Identifier(required=True)
    status = String(default="draft")
    total = Float()
    items = HasMany(OrderItem)

    def add_item(self, product_id, quantity=1):
        self.add_items(OrderItem(product_id=product_id, quantity=quantity))


# --8<-- [end:model]


# --8<-- [start:service]
@domain.application_service(part_of=Order)
class OrderService:
    @use_case
    def place_order(self, customer_id, items, total):
        order = Order(customer_id=customer_id, total=total)
        for item in items:
            order.add_item(**item)
        current_domain.repository_for(Order).add(order)
        return order


# --8<-- [end:service]


# --8<-- [start:endpoint]
app = FastAPI()
app.add_middleware(DomainContextMiddleware, route_domain_map={"/": domain})


@app.post("/orders")
async def create_order(payload: dict):
    service = OrderService()
    order = service.place_order(**payload)
    return {"id": order.id}


# --8<-- [end:endpoint]
