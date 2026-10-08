# --8<-- [start:domain]
from protean import Domain
from protean.fields import Float, Identifier, String, ValueObject

domain = Domain(name="Ordering")


@domain.value_object
class ShippingAddress:
    street: String(max_length=255, required=True)
    city: String(max_length=100, required=True)


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    total: Float(min_value=0.0)
    shipping_address: ValueObject(ShippingAddress, required=True)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_name: String(required=True)
    total: Float(required=True)


domain.init(traverse=False)
# --8<-- [end:domain]

# --8<-- [start:generate]
from protean.ir.generators.schema_writer import write_schemas

write_schemas(domain.to_ir(), ".protean")
# --8<-- [end:generate]

# --8<-- [start:validate]
import json

import jsonschema

with open(".protean/schemas/Order/events/OrderPlaced.v1.json") as f:
    schema = json.load(f)

payload = {
    "order_id": "order-123",
    "customer_name": "Alice",
    "total": 99.99,
}

jsonschema.validate(payload, schema)  # Passes
# --8<-- [end:validate]
