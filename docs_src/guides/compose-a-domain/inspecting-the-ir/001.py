# --8<-- [start:to-ir]
from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="Ecommerce")


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    total: Float(min_value=0.0)

    def place_order(self):
        self.raise_(
            OrderPlaced(
                order_id=self.id,
                customer_name=self.customer_name,
                total=self.total,
            )
        )


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_name: String(required=True)
    total: Float(required=True)


@domain.command(part_of=Order)
class PlaceOrder:
    customer_name: String(required=True)
    total: Float()


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def handle_place_order(self, command):
        order = Order(customer_name=command.customer_name, total=command.total)
        order.place_order()


domain.init(traverse=False)

ir = domain.to_ir()
# --8<-- [end:to-ir]

# --8<-- [start:print]
import json

print(json.dumps(ir, indent=2))
# --8<-- [end:print]

# --8<-- [start:write]
from pathlib import Path

Path("domain-ir.json").write_text(json.dumps(ir, indent=2, sort_keys=True))
# --8<-- [end:write]

# --8<-- [start:validate]
from jsonschema import validate

from protean.ir import load_schema

schema = load_schema()
validate(instance=ir, schema=schema)
# --8<-- [end:validate]
