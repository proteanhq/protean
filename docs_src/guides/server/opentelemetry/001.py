# --8<-- [start:fastapi-import]
from fastapi import FastAPI

# --8<-- [end:fastapi-import]
from protean import Domain, handle
from protean.fields import Float, Identifier, String

# --8<-- [start:instrument-import]
from protean.integrations.fastapi import instrument_app

# --8<-- [end:instrument-import]

# The page sets these keys under [telemetry] in domain.toml. The console
# exporter keeps the example from reaching for a collector.
domain = Domain(
    name="Orders",
    config={
        "command_processing": "sync",
        "telemetry": {
            "enabled": True,
            "service_name": "orders-api",
            "exporter": "console",
        },
    },
)


@domain.aggregate
class Order:
    customer = String(required=True)
    total = Float(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(identifier=True)
    customer = String(required=True)
    total = Float(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> str:
        order = Order(
            id=command.order_id, customer=command.customer, total=command.total
        )
        domain.repository_for(Order).add(order)
        return order.id


# --8<-- [start:instrument]
app = FastAPI()
instrument_app(app, domain)
# --8<-- [end:instrument]


@app.post("/orders", status_code=201)
def place_order(payload: dict) -> dict:
    with domain.domain_context():
        order_id = domain.process(
            PlaceOrder(customer=payload["customer"], total=payload["total"])
        )
    return {"id": order_id}
